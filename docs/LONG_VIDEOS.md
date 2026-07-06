# Long videos — how CineSFX stays fast and smart

**Short answer:** yes — for a long video CineSFX takes key-frames *smartly across
the whole thing*, not a naive frame-by-frame dump and not just the start. It scales
from a 5-second shot to a feature-length timeline without choking or blowing up
your AI bill.

Here is exactly what happens, and the knobs you can turn.

## 1. It never uploads or re-encodes the video

CineSFX reads each clip's **source file path** and in/out points straight from
Resolve. All analysis happens locally on that file. Nothing is exported.

## 2. Shot detection is bounded and accelerated

Scenes are found with content-aware shot detection (PySceneDetect) over **only the
clip's in/out range**, with two long-clip accelerations applied automatically:

- **Frame-skipping** (`analysis.frame_skip: -1` = auto): short clips are analysed
  frame-accurately; clips longer than `long_clip_threshold_seconds` (default 10
  min) are evaluated at ~`target_eval_fps` (default 4) frames/second. On 24fps
  footage that is ~6× faster with negligible impact on where cuts land.
- **Down-scaling** (`analysis.downscale_factor`): detection runs on smaller frames.

## 3. Smart, whole-video key-frame coverage

For every detected shot, a few tiny down-scaled key-frames are sampled *from the
middle of the shot* (via seek-based `ffmpeg`, cheap even on hour-long files). So the
key-frames are spread intelligently across the entire video — one small set per
actual shot — rather than uniformly guessing or only looking at the opening.

To keep the workload bounded on extreme cases, `analysis.max_scenes` (default 400)
caps the number of scenes. If a video has *more* shots than that, adjacent shots are
**merged into evenly-sized "super-scenes" that still span the whole clip** — you keep
full coverage, just grouped. Nothing at the end is dropped.

## 4. The AI is called in small batches

This is the key to long videos being affordable. Instead of sending hundreds of
frames in one giant request, scenes are grouped into batches of
`runtime.scenes_per_brain_batch` (default 12) and the brain is called once per
batch. Each request stays small and within context limits, and one failing batch
never kills the whole clip. Cues keep their real scene index, so timing stays exact.

## 5. Clips are processed in parallel + cached

- Multiple clips are analysed concurrently (`runtime.max_workers`).
- Scene detection + key-frames are cached by content hash, so re-running a long
  timeline only does new work.
- Only the *chosen* sound files are downloaded, and those are cached too.

## Tuning cheat-sheet (`config.yaml`)

| Setting | Effect | Default |
|---|---|---|
| `analysis.frame_skip` | `-1` auto; `0` frame-accurate; `N` skip N frames | `-1` |
| `analysis.long_clip_threshold_seconds` | when auto-skip kicks in | `600` |
| `analysis.target_eval_fps` | frames/sec evaluated on long clips | `4.0` |
| `analysis.downscale_factor` | detection frame down-scaling | `2` |
| `analysis.max_scenes` | cap; extra shots merged (coverage kept) | `400` |
| `analysis.frames_per_scene` | key-frames sent per scene | `2` |
| `runtime.scenes_per_brain_batch` | scenes per AI call (cost control) | `12` |
| `runtime.max_workers` | clips analysed in parallel | `4` |

### Rough guidance
- **Whole feature, budget-conscious:** raise `target_eval_fps` down to `2`, keep
  `frames_per_scene: 1`, `scenes_per_brain_batch: 16`.
- **Maximum precision on a short hero shot:** `frame_skip: 0`,
  `frames_per_scene: 3`.
