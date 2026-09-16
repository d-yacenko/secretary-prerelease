/// Plays a local audio file to completion or until [stop] is called.
abstract class SpeechPlayer {
  Future<void> playFile(String path);

  Future<void> stop();

  Future<void> dispose();
}
