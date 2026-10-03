package expo.modules.vestaopenlink

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Build
import expo.modules.kotlin.functions.Queues
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

class VestaOpenLinkModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("VestaOpenLink")

    // FLAG_ACTIVITY_REQUIRE_NON_BROWSER exists from Android 11; below it no
    // intent can skip the browser, so the caller falls back to its own.
    AsyncFunction("openInOwningAppAsync") { url: String ->
      if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
        false
      } else {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
          .addCategory(Intent.CATEGORY_BROWSABLE)
          .addFlags(Intent.FLAG_ACTIVITY_REQUIRE_NON_BROWSER)
        try {
          appContext.throwingActivity.startActivity(intent)
          true
        } catch (_: ActivityNotFoundException) {
          false
        }
      }
    }.runOnQueue(Queues.MAIN)
  }
}
