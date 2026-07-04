"""
Energy-based Voice Activity Detection (VAD) for LiveKit Agents.

Replaces Silero VAD (too slow on CPU) with a fast energy-based detector
using audioop.rms() — pure C under the hood, no compilation needed.

Usage:
    from energy_vad import EnergyVAD
    proc.userdata["vad"] = EnergyVAD(
        threshold=100,           # RMS energy threshold (16-bit audio)
        min_speech_duration=0.3,
        min_silence_duration=0.8,
    )
"""

import asyncio
import logging
import time
import audioop
from collections import deque
from livekit import rtc
from livekit.agents import vad

logger = logging.getLogger(__name__)


class EnergyVAD(vad.VAD):
    def __init__(
        self,
        *,
        threshold: int = 100,
        min_speech_duration: float = 0.3,
        min_silence_duration: float = 0.8,
        prefix_padding_duration: float = 0.5,
        max_buffered_speech: float = 60.0,
        activation_threshold: int | None = None,
        deactivation_threshold: int | None = None,
    ):
        self._threshold = threshold
        self._activation_threshold = activation_threshold or threshold
        self._deactivation_threshold = deactivation_threshold or int(threshold * 0.75)
        self._min_speech_duration = min_speech_duration
        self._min_silence_duration = min_silence_duration
        self._prefix_padding_duration = prefix_padding_duration
        self._max_buffered_speech = max_buffered_speech
        super().__init__(capabilities=vad.VADCapabilities(update_interval=0.03))

    @property
    def model(self) -> str:
        return "energy-based"

    @property
    def provider(self) -> str:
        return "builtin"

    def stream(self) -> "EnergyVADStream":
        return EnergyVADStream(self)


class EnergyVADStream(vad.VADStream):
    def __init__(self, vad_inst: EnergyVAD):
        super().__init__(vad_inst)
        self._vad: EnergyVAD = vad_inst

    async def _main_task(self) -> None:
        vad_inst = self._vad
        bytes_per_sample = 2  # S16LE

        # State
        is_speaking = False
        speech_frames: list[rtc.AudioFrame] = []
        consecutive_speech = 0
        consecutive_silence = 0
        total_processed = 0
        last_inference_time = time.monotonic()

        # Prefix buffer — keeps last ~0.5s of audio so we can prepend it
        # when speech starts (avoids cutting off the first word)
        prefix_max_frames = int(vad_inst._prefix_padding_duration / 0.03) + 5
        prefix_buffer: deque[rtc.AudioFrame] = deque(maxlen=prefix_max_frames)

        async for item in self._input_ch:
            if isinstance(item, vad.VADStream._FlushSentinel):
                if speech_frames:
                    self._emit_end(speech_frames, silence_duration=0.0)
                    speech_frames = []
                continue

            frame: rtc.AudioFrame = item
            total_processed += 1
            num_samples = len(frame.data) // bytes_per_sample
            rate = frame.sample_rate
            frame_duration = num_samples / (rate * frame.num_channels)

            # Get mono PCM data
            if frame.num_channels == 1:
                pcm = frame.data
            else:
                pcm = audioop.tomono(frame.data, bytes_per_sample, 0.5, 0.5)

            # Calculate RMS energy
            rms = audioop.rms(pcm, bytes_per_sample)

            # Determine speech vs silence with hysteresis
            threshold = (
                vad_inst._deactivation_threshold if is_speaking else vad_inst._activation_threshold
            )
            has_speech = rms >= threshold

            # Always maintain prefix buffer (even during speech, for next segment)
            prefix_buffer.append(frame)

            if has_speech:
                consecutive_speech += 1
                consecutive_silence = 0

                if not is_speaking:
                    speech_dur = consecutive_speech * frame_duration
                    if speech_dur >= vad_inst._min_speech_duration:
                        # START of speech — prepend prefix buffer
                        is_speaking = True
                        speech_frames = list(prefix_buffer)
                        self._emit_start()
                else:
                    speech_frames.append(frame)

            else:
                consecutive_silence += 1
                consecutive_speech = 0

                if is_speaking:
                    silence_dur = consecutive_silence * frame_duration
                    if silence_dur >= vad_inst._min_silence_duration:
                        # END of speech
                        self._emit_end(speech_frames, silence_duration=silence_dur)
                        speech_frames = []
                        is_speaking = False
                        consecutive_silence = 0
                    else:
                        # Still in brief silence gap — keep frame
                        speech_frames.append(frame)

            # Emit INFERENCE_DONE ~ once per second
            now = time.monotonic()
            if now - last_inference_time >= 1.0:
                last_inference_time = now
                self._emit_inference(rms, threshold, is_speaking)

        # End of input
        if speech_frames:
            self._emit_end(speech_frames, silence_duration=0.0)

    def _emit_start(self):
        self._event_ch.send_nowait(
            vad.VADEvent(
                type=vad.VADEventType.START_OF_SPEECH,
                samples_index=0,
                timestamp=time.time(),
                speech_duration=0.0,
                silence_duration=0.0,
                frames=[],
                probability=1.0,
                inference_duration=0.0,
                speaking=True,
            )
        )

    def _emit_end(self, frames: list[rtc.AudioFrame], silence_duration: float):
        total_duration = sum(len(f.data) / 2 / f.sample_rate for f in frames)
        self._event_ch.send_nowait(
            vad.VADEvent(
                type=vad.VADEventType.END_OF_SPEECH,
                samples_index=0,
                timestamp=time.time(),
                speech_duration=total_duration,
                silence_duration=silence_duration,
                frames=frames,
                probability=0.0,
                inference_duration=0.0,
                speaking=False,
                raw_accumulated_speech=total_duration,
                raw_accumulated_silence=silence_duration,
            )
        )

    def _emit_inference(self, rms: int, threshold: int, speaking: bool):
        self._event_ch.send_nowait(
            vad.VADEvent(
                type=vad.VADEventType.INFERENCE_DONE,
                samples_index=0,
                timestamp=time.time(),
                speech_duration=0.0,
                silence_duration=0.0,
                frames=[],
                probability=min(1.0, rms / (threshold * 2)),
                inference_duration=0.0,
                speaking=speaking,
            )
        )
