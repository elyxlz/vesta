from pywhispercpp.model import Model

model = None

def transcribe(audio_path: str) -> str:
    global model
    if not model:
        model = Model('base')
    segments = model.transcribe(audio_path)
    return ' '.join(segment.text for segment in segments)