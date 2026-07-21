import AVFoundation
import ExpoModulesCore
import UIKit

public final class VestaAudioSessionModule: Module {
  private lazy var transcriptFeedback = UIImpactFeedbackGenerator(style: .soft)

  public func definition() -> ModuleDefinition {
    Name("VestaAudioSession")

    AsyncFunction("setRecordingHapticsEnabledAsync") { (enabled: Bool) in
      try AVAudioSession.sharedInstance()
        .setAllowHapticsAndSystemSoundsDuringRecording(enabled)
    }

    AsyncFunction("transcriptHapticAsync") {
      let session = AVAudioSession.sharedInstance()
      if !session.allowHapticsAndSystemSoundsDuringRecording {
        try session.setAllowHapticsAndSystemSoundsDuringRecording(true)
      }
      self.transcriptFeedback.prepare()
      self.transcriptFeedback.impactOccurred(intensity: 0.65)
    }
    .runOnQueue(.main)
  }
}
