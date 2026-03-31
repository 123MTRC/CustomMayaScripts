# -*- coding: utf-8 -*-
"""
Sequence Animation Plugin - Playback Controller Module
管理动画播放状态：播放/暂停/停止、帧率、循环模式、帧索引推进。
"""

from enum import Enum
from typing import Callable, Optional


class PlaybackState(Enum):
    """播放状态枚举。"""
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class LoopMode(Enum):
    """循环模式枚举。"""
    LOOP = "loop"           # 循环播放
    ONCE = "once"           # 单次播放
    PING_PONG = "ping_pong" # 乒乓（来回播放）


class PlaybackController:
    """
    播放控制器：管理帧动画的播放逻辑。
    不直接操作图层，而是通过回调函数通知外部当前帧变化。
    """

    def __init__(self):
        self._state: PlaybackState = PlaybackState.STOPPED
        self._loop_mode: LoopMode = LoopMode.LOOP
        self._fps: int = 12
        self._current_index: int = 0
        self._total_frames: int = 0
        self._direction: int = 1  # 1 = 正向, -1 = 反向 (用于乒乓模式)

        # 回调：当帧变化时调用
        self._on_frame_changed: Optional[Callable[[int], None]] = None
        # 回调：当播放结束时调用（仅单次模式）
        self._on_playback_finished: Optional[Callable[[], None]] = None

    # ============================================================
    # 属性
    # ============================================================

    @property
    def state(self) -> PlaybackState:
        return self._state

    @property
    def is_playing(self) -> bool:
        return self._state == PlaybackState.PLAYING

    @property
    def is_paused(self) -> bool:
        return self._state == PlaybackState.PAUSED

    @property
    def is_stopped(self) -> bool:
        return self._state == PlaybackState.STOPPED

    @property
    def fps(self) -> int:
        return self._fps

    @fps.setter
    def fps(self, value: int):
        self._fps = max(1, min(60, value))

    @property
    def frame_interval_ms(self) -> int:
        """帧间隔，单位毫秒。"""
        return max(16, int(1000.0 / self._fps))

    @property
    def current_index(self) -> int:
        return self._current_index

    @current_index.setter
    def current_index(self, value: int):
        if self._total_frames > 0:
            self._current_index = max(0, min(value, self._total_frames - 1))
        else:
            self._current_index = 0

    @property
    def total_frames(self) -> int:
        return self._total_frames

    @total_frames.setter
    def total_frames(self, value: int):
        self._total_frames = max(0, value)
        if self._current_index >= self._total_frames:
            self._current_index = max(0, self._total_frames - 1)

    @property
    def loop_mode(self) -> LoopMode:
        return self._loop_mode

    @loop_mode.setter
    def loop_mode(self, mode: LoopMode):
        self._loop_mode = mode

    @property
    def progress(self) -> float:
        """当前播放进度 (0.0 ~ 1.0)。"""
        if self._total_frames <= 1:
            return 0.0
        return self._current_index / (self._total_frames - 1)

    # ============================================================
    # 回调设置
    # ============================================================

    def set_on_frame_changed(self, callback: Callable[[int], None]):
        """设置帧变化回调。callback 接收当前帧索引 (0-based)。"""
        self._on_frame_changed = callback

    def set_on_playback_finished(self, callback: Callable[[], None]):
        """设置播放结束回调（仅单次模式时触发）。"""
        self._on_playback_finished = callback

    # ============================================================
    # 播放控制
    # ============================================================

    def play(self):
        """开始/继续播放。"""
        if self._total_frames == 0:
            return
        self._state = PlaybackState.PLAYING
        if self._direction == 0:
            self._direction = 1

    def pause(self):
        """暂停播放。"""
        if self._state == PlaybackState.PLAYING:
            self._state = PlaybackState.PAUSED

    def stop(self):
        """停止播放，重置到第一帧。"""
        self._state = PlaybackState.STOPPED
        self._current_index = 0
        self._direction = 1
        self._notify_frame_changed()

    def toggle_play_pause(self):
        """切换播放/暂停。"""
        if self._state == PlaybackState.PLAYING:
            self.pause()
        else:
            self.play()

    # ============================================================
    # 帧导航
    # ============================================================

    def go_to_frame(self, index: int):
        """
        跳转到指定帧。

        Args:
            index: 帧索引 (0-based)
        """
        if self._total_frames == 0:
            return
        self._current_index = max(0, min(index, self._total_frames - 1))
        self._notify_frame_changed()

    def next_frame(self):
        """前进一帧。"""
        if self._total_frames == 0:
            return
        if self._current_index < self._total_frames - 1:
            self._current_index += 1
        elif self._loop_mode == LoopMode.LOOP:
            self._current_index = 0
        self._notify_frame_changed()

    def prev_frame(self):
        """后退一帧。"""
        if self._total_frames == 0:
            return
        if self._current_index > 0:
            self._current_index -= 1
        elif self._loop_mode == LoopMode.LOOP:
            self._current_index = self._total_frames - 1
        self._notify_frame_changed()

    def go_to_first(self):
        """跳转到第一帧。"""
        self.go_to_frame(0)

    def go_to_last(self):
        """跳转到最后一帧。"""
        self.go_to_frame(self._total_frames - 1)

    # ============================================================
    # 帧推进（由 QTimer 调用）
    # ============================================================

    def advance_frame(self):
        """
        推进一帧。由外部定时器周期调用。
        根据循环模式决定行为。
        """
        if self._state != PlaybackState.PLAYING:
            return

        if self._total_frames == 0:
            return

        next_index = self._current_index + self._direction

        if self._loop_mode == LoopMode.LOOP:
            # 循环模式：到末尾后回到开头
            if next_index >= self._total_frames:
                next_index = 0
            elif next_index < 0:
                next_index = self._total_frames - 1

        elif self._loop_mode == LoopMode.ONCE:
            # 单次模式：到末尾后停止
            if next_index >= self._total_frames or next_index < 0:
                self._state = PlaybackState.STOPPED
                if self._on_playback_finished:
                    self._on_playback_finished()
                return

        elif self._loop_mode == LoopMode.PING_PONG:
            # 乒乓模式：到边界后反向
            if next_index >= self._total_frames:
                self._direction = -1
                next_index = self._total_frames - 2
                if next_index < 0:
                    next_index = 0
            elif next_index < 0:
                self._direction = 1
                next_index = 1
                if next_index >= self._total_frames:
                    next_index = 0

        self._current_index = next_index
        self._notify_frame_changed()

    # ============================================================
    # 内部方法
    # ============================================================

    def _notify_frame_changed(self):
        """
        通知帧变化。
        容错：回调异常不会传播，防止外部错误导致播放器状态混乱。
        """
        if self._on_frame_changed:
            try:
                self._on_frame_changed(self._current_index)
            except Exception as e:
                print(f"[SequenceAnimation] 帧变化回调异常: {e}")
