// Plain-language wording for first-time viewers. The engine's own sentences stay available in Expert mode.

import type { AgentEvent, Incident } from './api'

/** Turn an engine fix description into a plain one. */
export function plainAction(text: string): string {
  let m = text.match(/^Move (\d+) phone\(s\) to (Tower \w)/)
  if (m) return `Hand ${m[1]} user${m[1] === '1' ? '' : 's'} over to ${m[2]}`
  m = text.match(/^Point (Tower \w) beam \d+ at (\d+) phone\(s\)/)
  if (m) return `Re-aim ${m[1]}'s beam for ${m[2]} user${m[2] === '1' ? '' : 's'}`
  m = text.match(/^(Raise|Lower) (Tower \w) power by ([\d.]+) dB/)
  if (m) return `${m[1] === 'Raise' ? 'Increase' : 'Reduce'} ${m[2]}'s transmit power (${m[1] === 'Raise' ? '+' : '−'}${m[3]} dB)`
  m = text.match(/^Tilt (Tower \w) (down|up) by ([\d.]+) degrees/)
  if (m) return `Tilt ${m[1]}'s antenna ${m[2]} ${m[3]}°`
  m = text.match(/^Shift edge phones from (Tower \w) toward (Tower \w)/)
  if (m) return `Move users at the edge of ${m[1]}'s area to ${m[2]}`
  return text
}

export const CAUSE: Record<string, { title: string; explain: string }> = {
  blockage: {
    title: 'Signal path blocked',
    explain: 'Something physical (a bus, truck, crowd or board) is standing between the tower and these users.',
  },
  wrong_beam: {
    title: 'Beam pointing the wrong way',
    explain: 'The tower is aiming its narrow beam slightly away from these users.',
  },
  interference: {
    title: 'Interference',
    explain: 'Another transmitter is too loud here and is drowning out the right tower.',
  },
  congestion: {
    title: 'Tower overloaded',
    explain: 'Too many people are sharing one tower, so everyone gets a slice that is too small.',
  },
  none: { title: 'Normal fluctuation', explain: 'Signal varied a little; nothing needs fixing.' },
  unknown: { title: 'Cause unclear', explain: 'The evidence is not strong enough to name a cause yet.' },
}

export interface PlainStep { key: string; icon: string; label: string; doing: string }

export const PLAIN_STEPS: PlainStep[] = [
  { key: 'observe', icon: '👁', label: 'Detect', doing: 'Watching every user’s signal once a second.' },
  { key: 'diagnose', icon: '🩺', label: 'Diagnose', doing: 'Working out the cause with the diagnosis model (LWM + classifier).' },
  { key: 'twin', icon: '🧪', label: 'Test on twin', doing: 'Trying possible fixes on the digital twin, a virtual copy of this street, before touching the real network.' },
  { key: 'safety', icon: '🛡', label: 'Safety check', doing: 'Checking each fix against hard limits: power, cooldowns, harm to other users, the hospital’s reserve.' },
  { key: 'human', icon: '🙋', label: 'Your approval', doing: 'This change is larger than the agent may make alone, so it is waiting for you.' },
  { key: 'act', icon: '🔧', label: 'Apply', doing: 'Applying the chosen fix to the network.' },
  { key: 'verify', icon: '✅', label: 'Verify', doing: 'Measuring the real result and comparing it with what the twin predicted. If it fell short, it is undone.' },
]

const STAGE_TO_PLAIN: Record<string, string> = {
  detect: 'observe', note: 'observe', diagnose: 'diagnose', rehearse: 'twin', plan: 'safety', check: 'safety',
  review: 'safety', escalate: 'human', approve: 'human', act: 'act', withdraw: 'act', verify: 'verify',
  undo: 'verify', resolve: 'verify',
}
export const plainStepOf = (stage: string) => STAGE_TO_PLAIN[stage] ?? 'observe'

export function incidentHeadline(i: Incident): string {
  const n = i.phones.length
  const who = `${n} user${n === 1 ? '' : 's'} ${i.place}`
  switch (i.status) {
    case 'new': return `${who} lost good service. The agent is working on it.`
    case 'verifying': return `A fix is in place for ${who}. Checking that it really worked.`
    case 'waiting_human': return `The agent has a fix for ${who} and needs your approval.`
    case 'escalated': return `No safe automatic fix for ${who}. The agent handed it to you.`
    case 'fixed': return `Service restored for ${who}.`
    case 'closing': return `The cause has gone, so the agent is undoing its temporary fix.`
    case 'false_alarm': return `Small dip for ${who}. Normal fluctuation, no action needed.`
    default: return i.outcome === 'withdrawn' || i.outcome === 'fixed'
      ? `Resolved: ${who} are back to normal.` : `Closed: ${who}.`
  }
}

/** A one-line, plain description of one engine step, for the activity feed. */
export function plainEvent(e: AgentEvent): string | null {
  const t = e.text
  switch (e.stage) {
    case 'detect': {
      const m = t.match(/^(\d+) (more )?phone\(s\) (.*?) lost service/)
      if (m) return m[2] ? `${m[1]} more users nearby lost service.` : `${m[1]} users ${m[3]} lost good service.`
      return t
    }
    case 'diagnose': {
      const m = t.match(/Likely cause: ([\w ]+) \((\d+)% sure\)/)
      if (m) return `Cause found: ${CAUSE[m[1].replace(' ', '_')]?.title ?? m[1]} (${m[2]}% confidence).`
      if (t.startsWith('Looks like normal variation')) return 'Only a normal fluctuation. No action needed.'
      return null
    }
    case 'rehearse': {
      const m = t.match(/Rehearsed (\d+) fixes on the twin\. Best: (.*?) \(([+-][\d.]+) dB/)
      if (m) return `Tested ${m[1]} possible fixes on the digital twin. Best: ${plainAction(m[2])}.`
      return null
    }
    case 'check':
      if (t.startsWith('Approved')) return 'Passed every safety check.'
      if (t.startsWith('Rejected')) {
        const m = t.match(/^Rejected: (.*?), because (.*)\.$/)
        return m ? `Ruled out “${plainAction(m[1])}”: ${m[2]}.` : null
      }
      if (t.startsWith('Re-checked')) return t
      return null
    case 'plan': {
      const m = t.match(/^Planner picked: (.*?)\. (.*)$/)
      return m ? `Chose: ${plainAction(m[1])}. ${m[2]}` : t
    }
    case 'review':
      return t.replace('Safety adviser agrees:', 'Safety review approved:').replace('Safety adviser objects:', 'Safety review objected:')
    case 'escalate':
      if (t.startsWith('Asking a person to approve')) return 'Asked you to approve the change.'
      return t.replace(/Asking the operator to take over\.?/, 'Handed to you.')
    case 'approve': return t.replace('Operator approved', 'You approved').replace('Operator declined', 'You declined')
    case 'act': {
      const m = t.match(/^Applied: (.*?)( \(twin predicts ([+-][\d.]+) dB\))?\.$/)
      return m ? `Applied: ${plainAction(m[1])}.` : t
    }
    case 'verify': {
      const m = t.match(/Result: ([+-][\d.]+) dB measured vs ([+-][\d.]+) dB predicted\. Kept\./)
      return m ? `It worked: real improvement ${m[1]} dB (twin predicted ${m[2]} dB). Fix kept.` : t
    }
    case 'undo': {
      const m = t.match(/Result: ([+-][\d.]+) dB measured vs ([+-][\d.]+) dB predicted\. Undone, because (.*?)\./)
      return m ? `Fell short (${m[1]} dB real vs ${m[2]} dB predicted), so it was undone automatically: ${m[3]}.` : t
    }
    case 'withdraw': return 'The cause went away, so the temporary fix was removed and settings went back to normal.'
    case 'resolve': return t
    default: return null
  }
}
