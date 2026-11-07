"""Driving a real Rouh session with no browser and no microphone.

Everything Rouh does crosses one websocket: what it heard, what it said, what
it drew, which tools it called. So a client on that socket is having the whole
experience, and the two halves that were previously untestable stop being so:

- **Hearing** is tested by turning a written sentence into speech with
  ElevenLabs and pushing those audio frames in exactly as the microphone does.
  Rouh's own transcriber then has to get it back.
- **Speaking** is tested by capturing the audio it sends back and running it
  through a transcriber, then comparing that to the text it wrote.

Both halves cost real API calls, so nothing here runs as part of the unit
suite.
"""
