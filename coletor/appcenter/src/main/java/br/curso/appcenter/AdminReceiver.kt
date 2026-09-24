package br.curso.appcenter

import android.app.admin.DeviceAdminReceiver

/** Administrador do aparelho. Vira Device Owner com:
 *  adb shell dpm set-device-owner br.curso.appcenter/.AdminReceiver */
class AdminReceiver : DeviceAdminReceiver()
