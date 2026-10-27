import { useEffect, useRef, useState } from 'react'
import { clipUrl } from './api'

interface Props {
  runId: string
  version: number
  /** The step the user wants to see. The player animates its way there one clip at a time. */
  target: number
  ready: Set<number>
  /** Called when the canvas starts showing a step, so the code and panels stay in sync with the animation. */
  onShow: (index: number) => void
}

const FAST_RATE = 2.5

function once(el: HTMLVideoElement, event: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const done = () => {
      el.removeEventListener(event, done)
      el.removeEventListener('error', fail)
      resolve()
    }
    const fail = () => {
      el.removeEventListener(event, done)
      el.removeEventListener('error', fail)
      reject(new Error('video failed to load'))
    }
    el.addEventListener(event, done)
    el.addEventListener('error', fail)
  })
}

/**
 * Shows one Manim clip per step. Two stacked video elements take turns so switching clips never flashes black:
 * the next clip loads in the hidden one and is revealed once its first frame is ready.
 */
export default function Player({ runId, version, target, ready, onShow }: Props) {
  const a = useRef<HTMLVideoElement>(null)
  const b = useRef<HTMLVideoElement>(null)
  const [front, setFront] = useState(0)
  const [waitingFor, setWaitingFor] = useState<number | null>(null)
  const frontRef = useRef(0)
  const shown = useRef<{ key: string; index: number } | null>(null)
  const latest = useRef({ runId, version, target, ready, onShow })
  const running = useRef(false)

  useEffect(() => {
    latest.current = { runId, version, target, ready, onShow }
  })

  useEffect(() => {
    const present = async (run: string, ver: number, index: number, mode: 'play' | 'end', rate: number) => {
      const videos = [a.current!, b.current!]
      const back = 1 - frontRef.current
      const video = videos[back]
      video.src = clipUrl(run, ver, index)
      video.playbackRate = rate
      await once(video, 'loadeddata')
      if (mode === 'end') {
        video.currentTime = Math.max(0, video.duration - 0.04)
        await once(video, 'seeked')
      } else {
        await video.play()
      }
      frontRef.current = back
      setFront(back)
      videos[1 - back].pause()
      latest.current.onShow(index)
      if (mode === 'play') await once(video, 'ended')
    }

    const pending = () => {
      const l = latest.current
      const key = `${l.runId}/${l.version}`
      return shown.current?.key !== key || shown.current.index !== l.target
    }

    const loop = async () => {
      if (running.current) return
      running.current = true
      try {
        while (pending()) {
          const { runId: run, version: ver, target: want, ready: have } = latest.current
          const key = `${run}/${ver}`
          const current = shown.current?.key === key ? shown.current.index : null
          // Moving forward one step plays that step's clip. Anything else (a new run, a re-render, stepping
          // back) jumps straight to the end of the target clip, except the very first clip, which plays.
          const jump = current === null || want < current
          const next = jump ? want : current + 1
          if (!have.has(next)) {
            setWaitingFor(next)
            await new Promise((r) => setTimeout(r, 120))
            continue
          }
          setWaitingFor(null)
          const mode = jump && !(current === null && want === 0) ? 'end' : 'play'
          await present(run, ver, next, mode, !jump && want - next > 0 ? FAST_RATE : 1)
          shown.current = { key, index: next }
        }
      } catch {
        // A clip failed to load, usually because a newer run replaced it. The next change retries.
      } finally {
        running.current = false
        setWaitingFor(null)
      }
    }
    void loop()
  }, [runId, version, target])

  return (
    <div className="player">
      <video ref={a} className={front === 0 ? 'clip front' : 'clip'} muted playsInline preload="auto" />
      <video ref={b} className={front === 1 ? 'clip front' : 'clip'} muted playsInline preload="auto" />
      {waitingFor !== null && (
        <div className="player-wait" role="status">
          <span className="spinner" aria-hidden="true" />
          Rendering step {waitingFor + 1}
        </div>
      )}
    </div>
  )
}
