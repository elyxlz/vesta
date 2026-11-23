Pod::Spec.new do |spec|
  spec.name = "VestaMenuButton"
  spec.version = "1.0.0"
  spec.summary = "A tap target that opens a system menu at a chosen point"
  spec.description = "Opens a UIKit menu from a transparent button and lets the caller place the menu's attachment point outside the button."
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
