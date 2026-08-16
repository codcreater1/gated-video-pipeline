import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");

// i5-9300H, 4 çekirdek / 8 iş parçacığı. Remotion headless Chrome ile kare kare
// render eder; tüm çekirdekleri vermek makineyi kullanılamaz hale getirir.
Config.setConcurrency(3);

// Ara kareler harici diske yazılır — C:'de 12 GB kaldı ve 10 dakikalık bir bölüm
// 30fps'te 18.000 kare demek.
Config.setOutputLocation("D:/otomasyon-data/output");

// Kalite/boyut dengesi. Bedtime içeriği düşük hareketli, yüksek CRF sorun yaratmıyor.
Config.setCrf(23);

// Bölümler ffmpeg ile birleştirilerek derleme yapılacak; codec tutarlı olmalı.
Config.setCodec("h264");
