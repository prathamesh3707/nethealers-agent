"""LWM (Large Wireless Model) fingerprints for our simulated channels.

LWM (Alikhani, Charan, Alkhateeb, 2024; https://huggingface.co/wi-lab/lwm,
MIT licence) is a small transformer pre-trained on ray-traced channels. It
reads one tower-to-phone channel as a 32 x 32 grid (32 tower antennas x 32
subcarriers at 30 kHz spacing) and returns a 64-number summary.

The model classes below are copied from the LWM repository (MIT licence) so
the published weights load unchanged; only an `encode` method is added.
We build the 32 x 32 grid from our simulator's paths with the same formula
DeepMIMO uses: each path adds its amplitude, delay phase and array phase.
"""

from __future__ import annotations

import math
import urllib.request
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from ..sim.channel import Paths

WEIGHTS_URL = "https://huggingface.co/wi-lab/lwm/resolve/main/model_weights.pth"
DEFAULT_WEIGHTS = Path(__file__).resolve().parents[3] / "models" / "lwm" / "model_weights.pth"

N_ANT = 32
N_SUB = 32
SUBCARRIER_HZ = 30e3
PATCH = 16
NORM = 1e6  # LWM scales DeepMIMO channels by 1e6 before tokenizing

# ---------------------------------------------------------------- model (from wi-lab/lwm, MIT licence)

ELEMENT_LENGTH = 16
D_MODEL = 64
MAX_LEN = 129
N_LAYERS = 12
N_HEADS = 12
D_FF = D_MODEL * 4
D_K = D_MODEL // N_HEADS
D_V = D_MODEL // N_HEADS
DROPOUT = 0.1


class LayerNormalization(nn.Module):
    def __init__(self, d_model: int, eps: float = 1e-6) -> None:
        super().__init__()
        self.eps = eps
        self.alpha = nn.Parameter(torch.ones(d_model))
        self.bias = nn.Parameter(torch.zeros(d_model))

    def forward(self, x):
        mean = x.mean(dim=-1, keepdim=True)
        std = x.std(dim=-1, keepdim=True)
        return self.alpha * (x - mean) / (std + self.eps) + self.bias


class Embedding(nn.Module):
    def __init__(self, element_length, d_model, max_len):
        super().__init__()
        self.element_length = element_length
        self.d_model = d_model
        self.proj = nn.Linear(element_length, d_model)
        self.pos_embed = nn.Embedding(max_len, d_model)
        self.norm = LayerNormalization(d_model)

    def forward(self, x):
        seq_len = x.size(1)
        pos = torch.arange(seq_len, dtype=torch.long, device=x.device)
        pos = pos.unsqueeze(0).expand_as(x[:, :, 0])
        tok_emb = self.proj(x.float())
        embedding = tok_emb + self.pos_embed(pos)
        return self.norm(embedding)


class ScaledDotProductAttention(nn.Module):
    def forward(self, Q, K, V):
        scores = torch.matmul(Q, K.transpose(-1, -2)) / np.sqrt(D_K)
        attn = F.softmax(scores, dim=-1)
        context = torch.matmul(attn, V)
        return context, attn


class MultiHeadAttention(nn.Module):
    def __init__(self):
        super().__init__()
        self.W_Q = nn.Linear(D_MODEL, D_K * N_HEADS)
        self.W_K = nn.Linear(D_MODEL, D_K * N_HEADS)
        self.W_V = nn.Linear(D_MODEL, D_V * N_HEADS)
        self.linear = nn.Linear(N_HEADS * D_V, D_MODEL)
        self.norm = LayerNormalization(D_MODEL)
        self.dropout = nn.Dropout(DROPOUT)

    def forward(self, Q, K, V):
        residual, batch_size = Q, Q.size(0)
        q_s = self.W_Q(Q).view(batch_size, -1, N_HEADS, D_K).transpose(1, 2)
        k_s = self.W_K(K).view(batch_size, -1, N_HEADS, D_K).transpose(1, 2)
        v_s = self.W_V(V).view(batch_size, -1, N_HEADS, D_V).transpose(1, 2)
        context, attn = ScaledDotProductAttention()(q_s, k_s, v_s)
        output = context.transpose(1, 2).contiguous().view(batch_size, -1, N_HEADS * D_V)
        output = self.linear(output)
        return residual + self.dropout(output), attn


class PoswiseFeedForwardNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(D_MODEL, D_FF)
        self.fc2 = nn.Linear(D_FF, D_MODEL)
        self.dropout = nn.Dropout(DROPOUT)
        self.norm = LayerNormalization(D_MODEL)

    def forward(self, x):
        output = self.fc2(self.dropout(F.relu(self.fc1(x))))
        return x + self.dropout(output)


class EncoderLayer(nn.Module):
    def __init__(self):
        super().__init__()
        self.enc_self_attn = MultiHeadAttention()
        self.pos_ffn = PoswiseFeedForwardNet()
        self.norm = LayerNormalization(D_MODEL)

    def forward(self, enc_inputs):
        attn_outputs, attn = self.enc_self_attn(enc_inputs, enc_inputs, enc_inputs)
        attn_outputs = self.norm(attn_outputs)
        enc_outputs = self.pos_ffn(attn_outputs)
        return enc_outputs, attn


class lwm(torch.nn.Module):  # noqa: N801 (name kept so the published weights load)
    def __init__(self, element_length=16, d_model=64, max_len=129, n_layers=12):
        super().__init__()
        self.embedding = Embedding(element_length, d_model, max_len)
        self.layers = nn.ModuleList([EncoderLayer() for _ in range(n_layers)])
        self.linear = nn.Linear(d_model, d_model)
        self.norm = LayerNormalization(d_model)
        embed_weight = self.embedding.proj.weight
        d_model, n_dim = embed_weight.size()
        self.decoder = nn.Linear(d_model, n_dim, bias=False)
        self.decoder_bias = nn.Parameter(torch.zeros(n_dim))

    def encode(self, input_ids: torch.Tensor) -> torch.Tensor:
        """Run the encoder only. (B, 129, 16) tokens -> (B, 129, 64) embeddings; index 0 is CLS."""
        output = self.embedding(input_ids)
        for layer in self.layers:
            output, _ = layer(output)
        return output


# ---------------------------------------------------------------- our side: channels, tokens, fingerprints

def ensure_weights(path: Path = DEFAULT_WEIGHTS) -> Path:
    """Download the published LWM weights (2.5 MB) on first use."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(WEIGHTS_URL, tmp)
        tmp.rename(path)
    return path


def load_model(path: Path = DEFAULT_WEIGHTS, device: str = "cpu") -> lwm:
    model = lwm()
    state = torch.load(ensure_weights(path), map_location=device, weights_only=True)
    model.load_state_dict(state)
    model.eval()
    return model.to(device)


def channel_grids(paths: Paths, pairs: list[tuple[int, int]], boresight_deg: np.ndarray,
                  carrier_ghz: float) -> np.ndarray:
    """32 x 32 complex channel for each (tower, phone index) pair, DeepMIMO style.

    Each path contributes amplitude sqrt(10^(-loss/10)) with phase from its
    length, a delay phase across subcarriers, and a ULA phase across the
    tower's 32 half-wavelength-spaced antennas (angle relative to boresight).
    """
    out = np.zeros((len(pairs), N_ANT, N_SUB), dtype=np.complex64)
    if not pairs:
        return out
    lam = 299_792_458.0 / (carrier_ghz * 1e9)
    n = np.arange(N_ANT)[:, None]
    k = np.arange(N_SUB)[None, :]
    order = np.lexsort((paths.ue, paths.tower))
    t_sorted, u_sorted = paths.tower[order], paths.ue[order]
    for row, (t, u) in enumerate(pairs):
        lo = np.searchsorted(t_sorted * 1_000_000 + u_sorted, t * 1_000_000 + u, side="left")
        hi = np.searchsorted(t_sorted * 1_000_000 + u_sorted, t * 1_000_000 + u, side="right")
        idx = order[lo:hi]
        if len(idx) == 0:
            continue
        amp = np.sqrt(10 ** (-paths.loss_db[idx] / 10))
        phase0 = -2 * np.pi * (paths.length_m[idx] % lam) / lam
        tau = paths.delay_s[idx]
        az = np.radians(paths.aod_az[idx] - boresight_deg[t])
        el = np.radians(paths.aod_el[idx])
        spatial = np.sin(az) * np.cos(el)
        h = np.zeros((N_ANT, N_SUB), dtype=np.complex128)
        for a, p0, d, s in zip(amp, phase0, tau, spatial):
            h += a * np.exp(1j * (p0 - 2 * np.pi * k * SUBCARRIER_HZ * d - np.pi * n * s))
        out[row] = h.astype(np.complex64)
    return out


def tokenize(grids: np.ndarray) -> np.ndarray:
    """(N, 32, 32) complex -> (N, 129, 16) LWM tokens: CLS + 128 patches of [real | imag]."""
    flat = (grids.reshape(len(grids), -1) * NORM).astype(np.complex64)
    both = np.hstack([flat.real, flat.imag]).astype(np.float32)
    patches = both.reshape(len(grids), -1, PATCH)
    cls = np.full((len(grids), 1, PATCH), 0.2, dtype=np.float32)
    return np.concatenate([cls, patches], axis=1)


@torch.no_grad()
def fingerprints(model: lwm, grids: np.ndarray, batch: int = 256) -> np.ndarray:
    """64-number CLS fingerprint per channel grid."""
    if len(grids) == 0:
        return np.zeros((0, D_MODEL), dtype=np.float32)
    tokens = torch.from_numpy(tokenize(grids))
    outs = []
    for i in range(0, len(tokens), batch):
        outs.append(model.encode(tokens[i:i + batch])[:, 0].float().numpy())
    return np.concatenate(outs)


def lwm_features(model: lwm, world, base_result, ue_ids: list[int]):
    """LWM columns for these phones: fingerprint of the channel to the serving tower now
    (lwm_0..63), how it changed since `base_result` (lwmd_0..63), and their cosine (lwm_cos)."""
    import pandas as pd

    bores = np.array([t.boresight_deg for t in world.towers])
    idx = world.ue_index()
    fc = world.radio.carrier_ghz
    # Phones keep their list position when a crowd is appended, so base indices match.
    now = [(world.ues[idx[u]].serving, idx[u]) for u in ue_ids]
    base = [(int(base_result.serving[idx[u]]), idx[u]) for u in ue_ids]
    fp_now = fingerprints(model, channel_grids(world.last.paths, now, bores, fc))
    fp_base = fingerprints(model, channel_grids(base_result.paths, base, bores, fc))
    cos = (fp_now * fp_base).sum(1) / (np.linalg.norm(fp_now, axis=1) * np.linalg.norm(fp_base, axis=1) + 1e-9)
    out = pd.DataFrame(fp_now, columns=[f"lwm_{i}" for i in range(fp_now.shape[1])])
    delta = pd.DataFrame(fp_now - fp_base, columns=[f"lwmd_{i}" for i in range(fp_now.shape[1])])
    out["lwm_cos"] = cos
    return pd.concat([out, delta], axis=1)


def _check_constants():
    assert N_ANT * N_SUB * 2 // PATCH + 1 == MAX_LEN, "token count must match LWM's 129"
    assert math.isclose(N_SUB * SUBCARRIER_HZ, 0.96e6)


_check_constants()
