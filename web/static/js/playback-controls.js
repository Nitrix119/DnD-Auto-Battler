// ── Playback controls ───────────────────────────────────────────────────────
// A tiny transport over an ordered list of steps: current index, play/pause on a
// fixed timer, and stepping/seeking. It owns *timing and index only* — it never
// touches the DOM or canvas. Rendering is the caller's job via `onStep`, so this
// stays a small, single-responsibility unit.
//
// `onStep(index, { direction })` is called whenever the current step changes.
// `direction` is +1 / -1 / 0 (a seek), which the renderer uses to decide whether
// to (re)play a one-shot effect like a floating damage label.

const DEFAULT_INTERVAL_MS = 500; // 2 steps per second

export function createPlayer({ stepCount, onStep, onStateChange, intervalMs = DEFAULT_INTERVAL_MS }) {
    let index = 0;
    let timer = null;

    const atEnd = () => index >= stepCount - 1;
    const isPlaying = () => timer !== null;

    function emitState() {
        onStateChange?.({ index, playing: isPlaying(), atStart: index <= 0, atEnd: atEnd() });
    }

    function go(target, direction) {
        const clamped = Math.max(0, Math.min(stepCount - 1, target));
        if (clamped === index && direction !== 0) return; // already at an edge
        index = clamped;
        onStep(index, { direction });
        emitState();
    }

    function pause() {
        if (timer !== null) {
            clearInterval(timer);
            timer = null;
            emitState();
        }
    }

    function play() {
        if (isPlaying() || stepCount <= 1) return;
        if (atEnd()) go(0, 0); // replay from the top if parked at the end
        timer = setInterval(() => {
            if (atEnd()) {
                pause();
                return;
            }
            go(index + 1, +1);
        }, intervalMs);
        emitState();
    }

    return {
        stepForward: () => { pause(); go(index + 1, +1); },
        stepBackward: () => { pause(); go(index - 1, -1); },
        seek: (i) => { pause(); go(Number(i), 0); },
        play,
        pause,
        toggle: () => (isPlaying() ? pause() : play()),
        isPlaying,
        get index() { return index; },
        emitState,
    };
}
