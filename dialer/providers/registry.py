"""Which implementation an account gets. Simulation is chosen by env
(DIALER_SIMULATION=1, for tests and local work) or per account ("Practice
mode"), so a demo and a test take exactly the same code path as production."""
import os

from dialer.providers import fakes


def _truthy(v):
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def simulating(settings=None):
    if _truthy(os.environ.get("DIALER_SIMULATION")):
        return True
    return bool(settings is not None and getattr(settings, "simulation", False))


def fail_mode():
    """DIALER_SIMULATION_FAIL=twilio|elevenlabs|llm|stt -- drives the error UI."""
    return (os.environ.get("DIALER_SIMULATION_FAIL") or "").strip().lower()


def telephony(settings):
    if simulating(settings):
        return fakes.FakeTelephony(settings, fail_mode())
    from dialer.providers.twilio_live import TwilioTelephony
    return TwilioTelephony(settings)


def voice_agent(settings):
    if simulating(settings):
        return fakes.FakeVoiceAgent(settings, fail_mode())
    from dialer.providers.elevenlabs_live import ElevenLabsAgent
    return ElevenLabsAgent(settings)


def llm(settings):
    if simulating(settings):
        return fakes.FakeLLM(settings, fail_mode())
    from dialer.providers.llm_live import LiveLLM
    return LiveLLM(settings)


def transcriber(settings):
    if simulating(settings):
        return fakes.FakeTranscriber(settings, fail_mode())
    from dialer.providers.llm_live import LiveTranscriber
    return LiveTranscriber(settings)


def all_for(settings):
    return {"telephony": telephony(settings), "voice_agent": voice_agent(settings),
            "llm": llm(settings), "transcriber": transcriber(settings)}
