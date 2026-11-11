"""把 MP3 解成采样，再按播放设备要求的采样率送出去。

这台电脑上的声卡只接受 48000 Hz。Qt 自带播放器仍按文件原来的 44100 Hz
去打开设备，设备会一直停在空闲，进度条照走，但听不到声音。
"""

from __future__ import annotations

import array
import struct

import numpy as np
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat, QAudioSink, QMediaDevices, QtAudio


def render_pcm(
    samples: array.array,
    cursor: float,
    frames: int,
    step: float,
    channels: int,
    sample_format,
) -> tuple[bytes, float, bool]:
    count = len(samples)
    if count < 2 or frames <= 0 or step <= 0:
        return b"", cursor, True
    channels = max(1, channels)
    ended = False
    values: list[float] = []
    for _ in range(frames):
        if cursor >= count - 1:
            ended = True
            break
        index = int(cursor)
        frac = cursor - index
        left = samples[index]
        right = samples[min(index + 1, count - 1)]
        value = left + (right - left) * frac
        if value > 1.0:
            value = 1.0
        elif value < -1.0:
            value = -1.0
        values.extend([value] * channels)
        cursor += step
    if not values:
        return b"", cursor, True
    if sample_format == QAudioFormat.SampleFormat.Int16:
        pcm = struct.pack("<" + "h" * len(values), *[int(item * 32767) for item in values])
    else:
        pcm = struct.pack("<" + "f" * len(values), *values)
    return pcm, cursor, ended


def stretch_keep_pitch(samples, speed: float, sample_rate: int) -> np.ndarray:
    """把语速变成 speed 倍，音高保持不变。0.5 表示放慢到一半，时长加倍。"""
    audio = np.asarray(samples, dtype=np.float32)
    if audio.size < 8 or speed <= 0 or abs(speed - 1.0) < 0.02:
        return audio
    speed = min(2.0, max(0.5, speed))
    window = max(32, int(sample_rate * 0.030))
    if window % 2:
        window += 1
    synthesis_hop = max(8, int(sample_rate * 0.015))
    analysis_hop = max(1, int(round(synthesis_hop * speed)))
    search = int(sample_rate * 0.008)
    if audio.size < window * 2:
        return audio
    hann = np.hanning(window).astype(np.float32)
    frame_count = max(1, int((audio.size - window) / analysis_hop))
    out_length = frame_count * synthesis_hop + window
    mixed = np.zeros(out_length, dtype=np.float32)
    weight = np.zeros(out_length, dtype=np.float32)
    overlap = window - synthesis_hop
    squares = np.cumsum(np.concatenate(([0.0], audio.astype(np.float64) * audio)))
    previous = audio[:window].copy()
    for frame in range(frame_count):
        center = min(frame * analysis_hop, audio.size - window)
        if frame == 0:
            best = 0
        else:
            tail = previous[synthesis_hop : synthesis_hop + overlap]
            start = max(0, center - search)
            end = min(audio.size - window, center + search)
            region = audio[start : end + overlap]
            score = np.correlate(region, tail, mode="valid")
            count = max(0, end - start + 1)
            if score.size == 0 or count <= 0:
                best = center
            else:
                count = min(count, score.size)
                window_energy = squares[start + overlap : start + overlap + count] - squares[start : start + count]
                rated = score[:count] / (
                    np.sqrt(np.maximum(window_energy, 1e-8)) * (float(np.linalg.norm(tail)) + 1e-8)
                )
                best = start + int(np.argmax(rated))
        previous = audio[best : best + window].copy()
        dest = frame * synthesis_hop
        mixed[dest : dest + window] += previous * hann
        weight[dest : dest + window] += hann
    valid = weight > 1e-4
    mixed[valid] /= weight[valid]
    return np.clip(mixed, -1.0, 1.0)


def device_key(device) -> str:
    if device is None or device.isNull():
        return ""
    try:
        return bytes(device.id()).decode("utf-8", "ignore")
    except Exception:
        return str(device.description())


class ClipPlayer(QObject):
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    stateChanged = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rate = 1.0
        self.samples = array.array("f")
        self._source: np.ndarray | None = None
        self.cursor = 0.0
        self.source_rate = 44100
        self.duration_ms = 0
        self.output = QMediaDevices.defaultAudioOutput()
        self.out_format: QAudioFormat | None = None
        self.sink: QAudioSink | None = None
        self.io = None
        self._generation = 0
        self._expect_decode = False
        self._playing = False
        self._paused = False
        self.ended = False
        self.decoder = QAudioDecoder(self)
        self.decoder.bufferReady.connect(self._on_buffer)
        self.decoder.finished.connect(self._on_decoded)
        self.decoder.error.connect(self._on_error)
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._tick)

    def set_output(self, device) -> None:
        if device is None or device.isNull():
            return
        self.output = device
        if self._playing or self._paused:
            paused = self._paused
            self._open_sink()
            if paused and self.sink:
                self.sink.suspend()
                self._playing = False
                self._paused = True
                self.timer.stop()

    def set_rate(self, rate: float) -> None:
        if rate <= 0:
            return
        if abs(rate - self.rate) < 0.001:
            self.rate = rate
            return
        fraction = self.cursor / max(1, len(self.samples) - 1) if self.samples else 0.0
        self.rate = rate
        if self._source is not None and self._source.size:
            self._install_playback(fraction)
            self.ended = False
            self.durationChanged.emit(self.duration_ms)

    def play_file(self, path: str) -> None:
        self._expect_decode = False
        self._generation += 1
        self._close_sink()
        self.decoder.stop()
        self.samples = array.array("f")
        self._source = None
        self.cursor = 0.0
        self.ended = False
        self.duration_ms = 0
        self._paused = False
        self._expect_decode = True
        self.decoder.setSource(QUrl.fromLocalFile(path))
        self.decoder.start()

    def pause(self) -> None:
        if self.sink and self._playing:
            self.sink.suspend()
            self.timer.stop()
            self._playing = False
            self._paused = True
            self.stateChanged.emit("paused")

    def resume(self) -> None:
        if self._paused and self.sink:
            self.sink.resume()
            self.timer.start()
            self._paused = False
            self._playing = True
            self.stateChanged.emit("playing")
            return
        if self.samples and not self._playing:
            self._open_sink()

    def stop(self) -> None:
        self._expect_decode = False
        self._generation += 1
        self.decoder.stop()
        self._close_sink()
        self.stateChanged.emit("stopped")

    def seek(self, milliseconds: int) -> None:
        if self.source_rate <= 0 or not self.samples:
            return
        limit = max(0, len(self.samples) - 2)
        self.cursor = min(limit, max(0.0, milliseconds / 1000 * self.source_rate))
        self.ended = False

    def replay(self) -> bool:
        """从头再放当前已经解开的音频，不再重新解码。"""
        if not self.samples:
            return False
        self.seek(0)
        self._open_sink()
        self.positionChanged.emit(0)
        return self._playing

    def render(self, maxlen: int) -> bytes:
        fmt = self.out_format
        if fmt is None or maxlen <= 0 or not self.samples or self.ended:
            self.ended = True
            return b""
        frame_bytes = fmt.bytesPerFrame() or fmt.bytesPerSample() * max(1, fmt.channelCount())
        if frame_bytes <= 0:
            return b""
        frames = maxlen // frame_bytes
        step = self.source_rate / max(1, fmt.sampleRate())
        pcm, cursor, ended = render_pcm(
            self.samples,
            self.cursor,
            frames,
            step,
            fmt.channelCount(),
            fmt.sampleFormat(),
        )
        self.cursor = cursor
        self.ended = ended
        return pcm

    def _append(self, buffer) -> None:
        fmt = buffer.format()
        if fmt.sampleRate() > 0:
            self.source_rate = fmt.sampleRate()
        raw = bytes(buffer.constData())
        channels = max(1, fmt.channelCount())
        if fmt.sampleFormat() == QAudioFormat.SampleFormat.Float:
            count = len(raw) // 4
            values = struct.unpack("<" + "f" * count, raw[: count * 4])
        elif fmt.sampleFormat() == QAudioFormat.SampleFormat.Int16:
            count = len(raw) // 2
            values = [item / 32768 for item in struct.unpack("<" + "h" * count, raw[: count * 2])]
        else:
            return
        if channels == 1:
            self.samples.extend(values)
            return
        self.samples.extend(
            sum(values[index : index + channels]) / channels
            for index in range(0, len(values) - channels + 1, channels)
        )

    def _on_buffer(self) -> None:
        generation = self._generation
        while self.decoder.bufferAvailable():
            buffer = self.decoder.read()
            if generation != self._generation:
                return
            self._append(buffer)

    def _on_decoded(self) -> None:
        if not self._expect_decode:
            return
        self._expect_decode = False
        self._on_buffer()
        if not self.samples:
            self.failed.emit("这个文件没有解出声音。")
            self.stateChanged.emit("stopped")
            return
        self._generation += 1
        self._source = np.asarray(self.samples, dtype=np.float32).copy()
        self._install_playback(0.0)
        self.durationChanged.emit(self.duration_ms)
        self._open_sink()

    def _install_playback(self, fraction: float) -> None:
        source = self._source if self._source is not None else np.asarray(self.samples, dtype=np.float32)
        stretched = stretch_keep_pitch(source, self.rate, self.source_rate)
        self.samples = array.array("f", np.asarray(stretched, dtype=np.float32))
        self.duration_ms = int(len(self.samples) / max(1, self.source_rate) * 1000)
        limit = max(0, len(self.samples) - 2)
        self.cursor = min(limit, max(0.0, fraction * limit))

    def _on_error(self, *_args) -> None:
        message = self.decoder.errorString() or "无法解码这个音频。"
        self.failed.emit(message)
        self.stateChanged.emit("stopped")

    def _open_sink(self) -> None:
        self._close_sink()
        device = self.output
        if device is None or device.isNull():
            device = QMediaDevices.defaultAudioOutput()
            self.output = device
        if device is None or device.isNull():
            self.failed.emit("没有可用的播放设备。")
            return
        fmt = device.preferredFormat()
        if not fmt.isValid() or fmt.sampleRate() <= 0 or fmt.channelCount() <= 0:
            fmt = QAudioFormat()
            fmt.setSampleRate(48000)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        if not device.isFormatSupported(fmt):
            self.failed.emit(f"「{device.description()}」不接受这个音频格式。")
            return
        self.out_format = fmt
        self.ended = False
        self.sink = QAudioSink(device, fmt, self)
        self.sink.setVolume(1.0)
        self.io = self.sink.start()
        if self.io is None or self.sink.error() != QtAudio.Error.NoError:
            self.failed.emit("播放设备没有开始出声。")
            self._close_sink()
            return
        self._playing = True
        self._paused = False
        self.timer.start()
        self.stateChanged.emit("playing")

    def _close_sink(self) -> None:
        self.timer.stop()
        self._playing = False
        self._paused = False
        if self.sink:
            self.sink.stop()
            self.sink.deleteLater()
            self.sink = None
        self.io = None

    def _tick(self) -> None:
        if not self._playing or self.sink is None or self.io is None:
            return
        free = self.sink.bytesFree()
        if free > 0 and not self.ended:
            pcm = self.render(free)
            if pcm:
                self.io.write(pcm)
        position = int(self.cursor / self.source_rate * 1000) if self.source_rate else 0
        self.positionChanged.emit(min(position, self.duration_ms or position))
        if self.ended and self.sink.processedUSecs() > 150000:
            self._close_sink()
            self.stateChanged.emit("stopped")
            self.finished.emit()
