from __future__ import annotations

import asyncio
import inspect
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Awaitable, Callable

import structlog

from server.config import get_settings
from server.tts.voices import resolve_edge_voice

log = structlog.get_logger(__name__)

_audio_child_pids: set[int] = set()


def _win32_ffplay_subprocess_kw() -> dict:
    """Windows: CREATE_NO_WINDOW; optional SDL override (OpenClaw leaves SDL unset)."""
    if sys.platform != "win32":
        return {}
    s = get_settings()
    kw: dict = {}
    driver = (s.CRUX_SDL_AUDIODRIVER or "").strip().lower()
    valid = frozenset({"wasapi", "directsound", "winmm", "dummy"})
    if driver in valid:
        kw["env"] = {**os.environ, "SDL_AUDIODRIVER": driver}
    if s.CRUX_FFPLAY_WINDOWS_NO_WINDOW and hasattr(subprocess, "CREATE_NO_WINDOW"):
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kw


def _win32_schedule_ffplay_volume_fix(pid: int) -> None:
    """Raise ffplay.exe session to 100 percent in the Windows mixer (OpenClaw friday-speak)."""
    if sys.platform != "win32" or pid <= 0:
        return

    def _run() -> None:
        try:
            from pycaw.utils import AudioUtilities
        except ImportError:
            log.debug("pycaw_not_installed_skip_mixer_fix")
            return
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                for sess in AudioUtilities.GetAllSessions():
                    try:
                        if sess.Process and sess.Process.pid == pid and sess.SimpleAudioVolume:
                            cur = sess.SimpleAudioVolume.GetMasterVolume()
                            if cur < 0.99:
                                sess.SimpleAudioVolume.SetMasterVolume(1.0, None)
                                log.info(
                                    "ffplay_mixer_volume_normalized",
                                    pid=pid,
                                    was=round(float(cur), 2),
                                )
                            return
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(0.05)

    threading.Thread(target=_run, daemon=True).start()


def _ffplay_executable_ok(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    if sys.platform == "win32":
        return path.lower().endswith((".exe", ".bat", ".cmd")) or os.access(path, os.X_OK)
    return os.access(path, os.X_OK)


def resolve_ffplay() -> str | None:
    s = get_settings()
    explicit = (s.CRUX_FFPLAY_PATH or "").strip()
    if explicit:
        if _ffplay_executable_ok(explicit):
            log.debug("ffplay_resolved", source="CRUX_FFPLAY_PATH", path=explicit)
            return explicit
        log.warning("ffplay_path_invalid", path=explicit)
    for candidate in (
        shutil.which("ffplay"),
        "/opt/homebrew/bin/ffplay",
        "/usr/local/bin/ffplay",
    ):
        if candidate and _ffplay_executable_ok(candidate):
            log.debug("ffplay_resolved", source="PATH", path=candidate)
            return candidate
    log.error(
        "ffplay_resolve_failed",
        hint="Install ffmpeg, add ffplay to PATH, or set CRUX_FFPLAY_PATH to ffplay.exe",
    )
    return None


def normalize_for_speech(text: str) -> str:
    t = text.strip()
    t = re.sub(r"[`*_#>\[\]()]", " ", t)
    t = re.sub(r"https?://\S+", "link", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip() or " "


def kill_all_audio() -> None:
    try:
        subprocess.run(
            ["pkill", "-f", "ffplay.*crux-tts"],
            check=False,
            capture_output=True,
        )
    except OSError as e:
        log.warning("pkill_ffplay_failed", err=str(e))
    for pid in list(_audio_child_pids):
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    _audio_child_pids.clear()


def _notify_macos(message: str) -> None:
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "Crux"'],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass


def say_playback_available() -> bool:
    s = get_settings()
    explicit = (s.CRUX_SAY_PATH or "").strip()
    if explicit and os.path.isfile(explicit) and os.access(explicit, os.X_OK):
        return True
    return bool(shutil.which("say"))


def edge_playback_available() -> bool:
    return resolve_ffplay() is not None


async def playback_say(
    text: str,
    voice: str,
    wpm: int,
    generation_ok: Callable[[], bool | Awaitable[bool]],
) -> float:
    settings = get_settings()
    say_bin = shutil.which("say")
    explicit = (settings.CRUX_SAY_PATH or "").strip()
    if explicit and os.path.isfile(explicit) and os.access(explicit, os.X_OK):
        say_bin = explicit
    if not say_bin:
        log.error("say_binary_not_found")
        if settings.CRUX_TTS_FALLBACK == "notify":
            _notify_macos("Crux could not find the macOS say command.")
        return 0.0

    if not await _eval_gen_ok(generation_ok):
        return 0.0

    proc = await asyncio.create_subprocess_exec(
        say_bin,
        "-v",
        voice,
        "-r",
        str(wpm),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    _audio_child_pids.add(proc.pid)
    try:
        assert proc.stdin is not None
        proc.stdin.write(text.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        await proc.stdin.wait_closed()
        await proc.wait()
    finally:
        _audio_child_pids.discard(proc.pid)
    return 0.0


async def playback_edge(
    text: str,
    *,
    voice: str,
    rate: str,
    pitch: str,
    stream: bool,
    generation_ok: Callable[[], bool | Awaitable[bool]],
) -> float:
    settings = get_settings()
    if not await _eval_gen_ok(generation_ok):
        return 0.0

    v = resolve_edge_voice(voice)
    ffplay = resolve_ffplay()
    if not ffplay:
        log.error("ffplay_not_found_install_ffmpeg_or_set_CRUX_FFPLAY_PATH")
        if settings.CRUX_TTS_FALLBACK == "notify":
            _notify_macos("Crux could not find ffplay. Install ffmpeg or set CRUX_FFPLAY_PATH.")
        return 0.0

    try:
        if stream:
            return await _stream_ffplay(text, v, rate, pitch, generation_ok, ffplay)
        return await _file_ffplay(text, v, rate, pitch, generation_ok, ffplay)
    except Exception as e:
        log.exception("tts_edge_failed", err=str(e))
        if settings.CRUX_TTS_FALLBACK == "notify":
            _notify_macos("Crux could not speak via Edge TTS.")
        return 0.0


async def _eval_gen_ok(gen_ok: Callable[[], bool | Awaitable[bool]]) -> bool:
    r = gen_ok()
    if inspect.isawaitable(r):
        return bool(await r)
    return bool(r)


async def generation_allowed(gen_ok: Callable[[], bool | Awaitable[bool]]) -> bool:
    """Public wrapper for providers outside this module (e.g. ElevenLabs)."""
    return await _eval_gen_ok(gen_ok)


async def playback_mp3_bytes(
    data: bytes,
    generation_ok: Callable[[], bool | Awaitable[bool]],
) -> float:
    """Play MP3 bytes via ffplay (stdin pipe on Unix; temp file on Windows for reliability)."""
    settings = get_settings()
    if not await _eval_gen_ok(generation_ok):
        return 0.0
    ffplay = resolve_ffplay()
    if not ffplay:
        log.error("ffplay_not_found_install_ffmpeg_or_set_CRUX_FFPLAY_PATH")
        if settings.CRUX_TTS_FALLBACK == "notify":
            _notify_macos("Crux could not find ffplay. Install ffmpeg or set CRUX_FFPLAY_PATH.")
        return 0.0

    # Windows: asyncio subprocess + ffplay reading MP3 from stdin often yields no audible output
    # (pipe/probe/format edge cases). File-based playback matches the Edge non-stream path.
    if sys.platform == "win32":
        path: str | None = None
        try:
            log.info(
                "playback_mp3_win32_start",
                ffplay=ffplay,
                mp3_bytes=len(data),
            )
            with tempfile.NamedTemporaryFile(suffix=".mp3", prefix="crux-tts-", delete=False) as f:
                path = f.name
                f.write(data)
            if not await _eval_gen_ok(generation_ok):
                log.info("playback_mp3_win32_skipped", reason="generation_preempted_after_write")
                return 0.0
            # OpenClaw friday-speak _play_ffplay: quiet log, positional mp3 path, stdio DEVNULL.
            proc = await asyncio.create_subprocess_exec(
                ffplay,
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                path,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                **_win32_ffplay_subprocess_kw(),
            )
            _audio_child_pids.add(proc.pid)
            try:
                _win32_schedule_ffplay_volume_fix(proc.pid)
                await proc.wait()
                log.info(
                    "playback_mp3_win32_done",
                    returncode=proc.returncode,
                    temp_path=path,
                )
                if proc.returncode not in (0, None):
                    log.warning("ffplay_mp3_exit", returncode=proc.returncode)
            finally:
                _audio_child_pids.discard(proc.pid)
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        return 0.0

    proc = await asyncio.create_subprocess_exec(
        ffplay,
        "-nodisp",
        "-autoexit",
        "-loglevel",
        "error",
        "-window_title",
        "crux-tts",
        "-f",
        "mp3",
        "-i",
        "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        **_win32_ffplay_subprocess_kw(),
    )
    _audio_child_pids.add(proc.pid)
    try:
        if sys.platform == "win32":
            _win32_schedule_ffplay_volume_fix(proc.pid)
        chunk_size = 32_768
        offset = 0
        while offset < len(data):
            if not await _eval_gen_ok(generation_ok):
                log.info("playback_mp3_preempted", offset=offset, total=len(data))
                break
            end = min(offset + chunk_size, len(data))
            assert proc.stdin is not None
            proc.stdin.write(data[offset:end])
            await proc.stdin.drain()
            offset = end
        if proc.stdin:
            proc.stdin.close()
            await proc.stdin.wait_closed()
        await proc.wait()
        stderr = await proc.stderr.read() if proc.stderr else b""
        if proc.returncode not in (0, None):
            log.warning(
                "ffplay_mp3_exit",
                returncode=proc.returncode,
                stderr=(stderr.decode("utf-8", errors="replace")[:800] if stderr else ""),
            )
    finally:
        _audio_child_pids.discard(proc.pid)
    return 0.0


async def _stream_ffplay(
    text: str,
    voice: str,
    rate: str,
    pitch: str,
    generation_ok: Callable[[], bool | Awaitable[bool]],
    ffplay: str,
) -> float:
    import edge_tts

    proc = await asyncio.create_subprocess_exec(
        ffplay,
        "-nodisp",
        "-autoexit",
        "-loglevel",
        "quiet" if sys.platform == "win32" else "error",
        "-window_title",
        "crux-tts",
        "-i",
        "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        **_win32_ffplay_subprocess_kw(),
    )
    _audio_child_pids.add(proc.pid)
    try:
        if sys.platform == "win32":
            _win32_schedule_ffplay_volume_fix(proc.pid)
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        async for chunk in comm.stream():
            if not await _eval_gen_ok(generation_ok):
                break
            if chunk.get("type") == "audio" and chunk.get("data"):
                assert proc.stdin is not None
                proc.stdin.write(chunk["data"])
                await proc.stdin.drain()
        if proc.stdin:
            proc.stdin.close()
            await proc.stdin.wait_closed()
        await proc.wait()
    finally:
        _audio_child_pids.discard(proc.pid)
    return 0.0


async def _file_ffplay(
    text: str,
    voice: str,
    rate: str,
    pitch: str,
    generation_ok: Callable[[], bool | Awaitable[bool]],
    ffplay: str,
) -> float:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    with tempfile.NamedTemporaryFile(suffix=".mp3", prefix="crux-tts-", delete=False) as f:
        path = f.name
    try:
        await comm.save(path)
        if not await _eval_gen_ok(generation_ok):
            return 0.0
        log.info(
            "playback_edge_file_start",
            ffplay=ffplay,
            path=path,
            win32=sys.platform == "win32",
        )
        on_win = sys.platform == "win32"
        if on_win:
            proc = await asyncio.create_subprocess_exec(
                ffplay,
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                path,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                **_win32_ffplay_subprocess_kw(),
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                ffplay,
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "error",
                "-window_title",
                "crux-tts",
                "-i",
                path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        _audio_child_pids.add(proc.pid)
        if on_win:
            _win32_schedule_ffplay_volume_fix(proc.pid)
        await proc.wait()
        log.info("playback_edge_file_done", returncode=proc.returncode, win32=on_win)
        if proc.returncode not in (0, None):
            log.warning("playback_edge_ffplay_failed", returncode=proc.returncode)
        _audio_child_pids.discard(proc.pid)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return 0.0


class _SayFacade:
    def is_available(self) -> bool:
        return say_playback_available()

    async def __call__(
        self,
        text: str,
        voice: str,
        wpm: int,
        generation_ok: Callable[[], bool | Awaitable[bool]],
    ) -> float:
        return await playback_say(text, voice, wpm, generation_ok)


class _EdgeFacade:
    def is_available(self) -> bool:
        return edge_playback_available()

    async def __call__(
        self,
        text: str,
        *,
        voice: str,
        rate: str,
        pitch: str,
        stream: bool,
        generation_ok: Callable[[], bool | Awaitable[bool]],
    ) -> float:
        return await playback_edge(
            text,
            voice=voice,
            rate=rate,
            pitch=pitch,
            stream=stream,
            generation_ok=generation_ok,
        )


speak_say = _SayFacade()
speak_edge = _EdgeFacade()
