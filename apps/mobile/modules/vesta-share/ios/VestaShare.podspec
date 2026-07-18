Pod::Spec.new do |spec|
  spec.name = "VestaShare"
  spec.version = "1.0.0"
  spec.summary = "Native Vesta share sheet metadata"
  spec.description = "Adds Vesta title and icon metadata to native share sheets."
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
