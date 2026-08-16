package expo.modules.vestashare

import android.content.Intent
import expo.modules.kotlin.functions.Queues
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

class VestaShareModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("VestaShare")

    // The Android sharesheet reports no completion result without a result
    // receiver, so the promise resolves once the chooser is presented.
    AsyncFunction("shareMessageAsync") { message: String, title: String ->
      val activity = appContext.throwingActivity
      val sendIntent = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_TEXT, message)
        putExtra(Intent.EXTRA_TITLE, title)
        putExtra(Intent.EXTRA_SUBJECT, title)
      }
      activity.startActivity(Intent.createChooser(sendIntent, title))
      mapOf("completed" to true, "activityType" to null)
    }.runOnQueue(Queues.MAIN)
  }
}
