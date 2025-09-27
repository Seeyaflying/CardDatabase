[app]
title = CardDatabase
package.name = carddatabase
package.domain = org.example
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 0.1
requirements = python3,kivy,pyjnius
orientation = portrait
fullscreen = 0

[buildozer]
log_level = 2
warn_on_root = 1

[app:android]
android.api = 31
android.minapi = 21
android.archs = arm64-v8a, armeabi-v7a
