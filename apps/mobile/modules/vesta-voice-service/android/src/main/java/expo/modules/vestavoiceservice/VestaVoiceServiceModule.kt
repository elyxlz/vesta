package expo.modules.vestavoiceservice

import android.content.Context
import android.content.Intent
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

class VestaVoiceServiceModule : Module() {
  private val context: Context
    get() = appContext.reactContext ?: throw Exceptions.ReactContextLost()

  override fun definition() = ModuleDefinition {
    Name("VestaVoiceService")

    AsyncFunction("startForegroundServiceAsync") { title: String, body: String ->
      val intent = Intent(context, VoiceForegroundService::class.java)
        .putExtra(VoiceForegroundService.EXTRA_TITLE, title)
        .putExtra(VoiceForegroundService.EXTRA_BODY, body)
      context.startForegroundService(intent)
    }

    AsyncFunction("stopForegroundServiceAsync") {
      context.stopService(Intent(context, VoiceForegroundService::class.java))
    }
  }
}
