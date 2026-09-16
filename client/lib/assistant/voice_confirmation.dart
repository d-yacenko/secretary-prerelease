enum VoiceConfirmation { approve, reject, unknown }

const voiceConfirmationApproveCommands = {
  'да',
  'отправляй',
  'подтверждаю',
  'да отправляй',
};

const voiceConfirmationRejectCommands = {'нет', 'не отправляй', 'отмена'};

const voiceConfirmationRetrySpeech =
    'Не понял подтверждение. Скажите «да» или «нет».';

const voiceApprovalUnarmedSpeech =
    'Сначала дослушайте текст, затем скажите «да» или «нет».';

final _terminalPunctuation = RegExp(r'[.!?…,;:]+$');
final _whitespace = RegExp(r'\s+');

/// Strict whole-command confirmation parser. No fuzzy/LLM classification.
VoiceConfirmation parseVoiceConfirmation(String transcript) {
  final normalized = normalizeVoiceConfirmation(transcript);
  if (voiceConfirmationApproveCommands.contains(normalized)) {
    return VoiceConfirmation.approve;
  }
  if (voiceConfirmationRejectCommands.contains(normalized)) {
    return VoiceConfirmation.reject;
  }
  return VoiceConfirmation.unknown;
}

String normalizeVoiceConfirmation(String transcript) {
  var text = transcript.trim().toLowerCase();
  text = text.replaceAll(_whitespace, ' ');
  text = text.replaceAll(_terminalPunctuation, '');
  return text.trim();
}
