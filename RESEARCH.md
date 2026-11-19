# Shortlist research and quality benchmarks

## What strong clippers do

| Reference | What it does | What it means for Shortlist |
| --- | --- | --- |
| OpusClip ClipAnything | Combines visual, audio and sentiment cues, and lets users describe moments in a prompt. | Review the visible action before writing the headline. User intent should eventually steer candidate retrieval as well as selection. [ClipAnything](https://www.opus.pro/clipanything) |
| Eklipse | Uses game-specific events, on-screen UI signals, and creator callouts. Its GTA guides discuss where to look for useful HUD elements. | Use reliable GTA telemetry or labeled HUD transitions for specific claims such as a finish, elimination or race placement. General motion alone cannot identify them. [Highlight detection](https://eklipse.gg/help/how-does-eklipse-ai-choose-highlights/) · [GTA VI guide](https://eklipse.gg/help/gta-vi-stream-best-practices-with-eklipse/) |
| Powder | Highlights heightened emotion in the audio feed and offers game-specific detection for supported titles. | Keep reaction detection as one independent signal. A strong reaction paired with visible action deserves more attention than either signal alone. [Powder AI Clips](https://www.powder.gg/feature/ai-clips) |

These are documented capabilities. The comparison contains no measured vendor accuracy, latency, or publication results.

## Research that informs the implementation

QVHighlights asks reviewers to mark relevant time spans and grade clip saliency. That is a closer fit for Shortlist than whole-video classification. Query-dependent video representation research also supports changing the selection when the desired moment changes, such as a near miss versus a funny reaction. Shortlist currently narrows the replay using motion, audio and speech, then checks candidate frames locally. Its replay-activity data is a scouting cue where available. [QVHighlights](https://arxiv.org/abs/2107.09609) · [Query-Dependent DETR](https://openaccess.thecvf.com/content/CVPR2023/html/Moon_Query-Dependent_Video_Representation_for_Moment_Retrieval_and_Highlight_Detection_CVPR_2023_paper.html)

SmolVLM2 has a small video-trained checkpoint suitable for a local starting point. Shortlist samples five ordered frames per shortlisted gaming moment and uses a small set of supported observations for reranking and headlines. Frame sampling can miss brief events, and the model can misidentify a vehicle or mistake a camera change for action. Qwen3-VL offers timestamp-oriented video reasoning and is a candidate for a future comparison on the same clips. Its published benchmark results do not establish GTA accuracy. [SmolVLM2](https://huggingface.co/blog/smolvlm2) · [Qwen3-VL technical report](https://arxiv.org/abs/2511.21631)

## How to judge the next release

1. Build a set of creator-owned replays with annotated racing, pursuit, collision, reaction and quiet intervals. Include multiple languages, both webcam and no-webcam streams, and repeated footage. Mark uncertainty when a claim such as losing race position cannot be confirmed.
2. Compare the same inputs across Shortlist with visual review enabled and disabled, OpusClip, and Eklipse. Hide which system created each clip. Measure total windows scanned, annotated events found, how many top-five clips reviewers would post, the proportion of accurate headlines, subtitle corrections, and time to first MP4. Report per stream and by event type.
3. Separate picking a good clip from predicting its distribution. For published Shorts, track stayed-to-watch and engaged views alongside audience retention. Compare against the same channel's baseline and record title, edit and posting differences that could affect the outcome. [YouTube Shorts analytics](https://support.google.com/youtube/answer/12220281)

## What the sample showed

On the user's replay, a three-minute scan near 14:00 produced five valid MP4s. The local model reviewed four candidates and consistently recognized a motorcycle on a dirt road. It did not establish a near crash or a change in race placement, and the reviewed clips shared the same suggested headline. This is evidence that the visual path works, with a clear gap in event precision and headline variety.

For that gap, prioritize denser frame sampling near likely outcomes and validate visible HUD transitions before making race-result claims. Audio classification is worth testing on stream footage to see whether a lightweight model such as YAMNet can separate laughter and impact sounds from ordinary voice peaks. For podcast layouts, TalkNet is a relevant baseline for choosing an active speaker in a multi-person shot. Both additions need task-specific evaluations before replacing the existing signal or crop. [YAMNet](https://www.tensorflow.org/hub/tutorials/yamnet) · [TalkNet](https://arxiv.org/abs/2107.06592)

### Event-centered review experiment

The next pass sampled five frames around a signal peak instead of spacing them uniformly through the clip. On the saved motorcycle clip, the model recognized the bike but reported a fall for both an earlier riding interval and the suspected incident. It did not reliably distinguish the two. Shortlist now requires a matching spoken cue before using a specific near-crash or bike-fall headline, and ordinary riding no longer earns a visual ranking boost. The sample remains an exploratory check. Race-position claims still need HUD or telemetry evidence and independent human labels.

### Race HUD and broader replay search

Local OCR read the saved bike clip as fifth of 14 before the selected eight-second anchor and sixth of 14 afterward. The model can now promote a position change when repeated reads agree on each side and the field size matches. Mixed readings, disconnected HUDs and disappearance do not establish why the position changed or whether the rider left the race. The detector currently expects the bottom-right HUD and a position fraction with nearby race context. [RapidOCR project](https://github.com/RapidAI/RapidOCR)

Automatic replay search can scout up to 24 windows of 40 seconds before transcribing the best windows. A faster plan remains available. These are coverage limits, and very long replays still have unsampled portions. The benchmark page collects randomized human ratings and supports competitor MP4s plus measured timings. No cross-product quality claim follows without real vendor outputs and human ratings.

On the sample replay, the Balanced plan read nine of twelve selected windows, produced three distinct MP4s, and delivered the first clip in 212.7 seconds on the local machine. The three selected clips lacked a readable race HUD. The verified 5th-to-6th change came from a separate, targeted read of the saved bike clip. The blind review interface was tested with local fixture MP4s, which do not count as vendor results.

### Measured replay coverage

After sharing the replay manifest between imports, a Balanced repeat on the same sample read 11 of 12 windows and delivered two distinct MP4s. The first arrived in 200 seconds, compared with 212.7 seconds in the earlier run. These are individual local runs. The new scan decoded approximately 440 seconds (0.514% of the replay). Its evaluation marked the labeled bike event as outside the scan. In this run, increasing coverage near the relevant section mattered more than reranking the returned candidates.

The label editor and evaluation manifest make this diagnosis repeatable. Record additional ordinary and event intervals on source footage before testing a ranking change. Keep a separate holdout for measuring gains. Finish the cross-tool comparison with real exports and independent human ratings. OpusClip requires an account to generate exports, and Eklipse documents that downloading clips requires Premium. [OpusClip plans](https://www.opus.pro/pricing) · [Eklipse account and plan requirements](https://eklipse.gg/help/is-eklipse-free-or-paid/)

The seed set contains visually reviewed intervals from the supplied bike replay and two edited GTA roleplay stream excerpts. It covers a HUD position change, a police van maneuver, a pursuit, and ordinary footage. Labels describe what was visible. They do not infer a completed escape, a crash, or a creator's reaction from the video title. The edited excerpts provide a small detector check rather than a representative benchmark of raw streams. [Bike replay](https://www.youtube.com/watch?v=qSyo5d-dVzA) · [Police-van excerpt](https://www.youtube.com/watch?v=MCP71ny8wAo) · [Pursuit excerpt](https://www.youtube.com/watch?v=Te-8Ysf1ICQ)

With visual review off, the two edited roleplay excerpts were each scanned for 120 seconds. The van maneuver reached the candidate set but was not exported. The pursuit was within scanned footage but missed by candidate detection. A subsequent Quick test on the bike replay got no readable windows from the public replay manifest, so it produced no comparable latency measurement. Shortlist now retries failed shared-manifest imports using a refreshed per-window request.

### Ranking regression

The ranking update preserves separate candidates that share a generic headline. When visual review is enabled, a verified race HUD change ranks ahead of unverified motion and reaction scores. On the same 120-second police van excerpt with visual review off, the labeled maneuver moved from missing the exports to the first exported MP4 (79–100 seconds). Three clips were exported, including one that still overlapped an ordinary label without a labeled event. The generic headline and ordinary pick show remaining quality gaps. [Ranking evaluation](benchmarks/ranking-regression.json)

### Sustained-action regression

Shortlist now compares several seconds of activity with the preceding quieter stretch, which can produce a candidate without a simultaneous loud reaction. Brief overlap can survive when two candidates have different centers. On the same 120-second roleplay excerpt with visual review off, the labeled pursuit moved from scanned but undetected to the third export (57–78 seconds). Five MP4s were exported, including one that overlapped only an ordinary label. Motion alone does not verify that a pursuit took place, so the generated headline stayed generic. [Pursuit evaluation](benchmarks/pursuit-regression.json)

### Gameplay headline evidence

The updated visual review samples the start, the signal peak and the end, and crops the model input toward gameplay to reduce corner-webcam interference. The exported framing is independent of the analysis crop. In two labeled checks, the model initially described the streamer in the police-van excerpt. The cropped review identified a police van and a highway but missed the sideways turn. In the pursuit excerpt, it described the player's car without identifying the pursuit. These checks show improved scene identification on the van sample, with event identification still unreliable on both excerpts. Shortlist now leaves weak or repeated automatic headlines blank rather than attaching the same generic hook to distinct clips.
