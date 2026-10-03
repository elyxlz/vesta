Pod::Spec.new do |spec|
  spec.name = "VestaOpenLink"
  spec.version = "1.0.0"
  spec.summary = "Open a web link in the app that owns it"
  spec.description = "Opens a universal link in its installed app and reports whether one did."
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
