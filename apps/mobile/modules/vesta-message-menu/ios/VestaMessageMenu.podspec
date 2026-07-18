Pod::Spec.new do |spec|
  spec.name = "VestaMessageMenu"
  spec.version = "1.0.0"
  spec.summary = "Native context menus for Vesta message bubbles"
  spec.description = "Provides stable UIKit targeted previews for Vesta chat bubbles."
  spec.author = "Vesta"
  spec.homepage = "https://vesta.run"
  spec.platforms = { ios: "16.4" }
  spec.source = { git: "" }
  spec.static_framework = true

  spec.dependency "ExpoModulesCore"
  spec.pod_target_xcconfig = {
    "DEFINES_MODULE" => "YES",
  }
  spec.source_files = "**/*.{h,m,mm,swift,hpp,cpp}"
end
