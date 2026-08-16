/**
 * Sahnenin dikey iskeleti. Tek kaynak.
 *
 * Bu değerler ayrı ayrı yazıldığında bir katman değiştiğinde figürler havada
 * kalıyordu (bkz. SceneView'daki `standOn` yorumu). Arka plan katmanları da
 * aynı çizgilere oturmak zorunda: ufuk çizgisi ile zemin arasında boşluk
 * kalırsa arazi siluetinin altı gökyüzü rengiyle görünür.
 */

/** Karakterlerin ayak bastığı çizgi (yüzde). */
export const BASELINE_PCT = 72;

/** Zeminin başladığı çizgi. Arazi siluetleri bunun ARKASINDA biter. */
export const GROUND_TOP_PCT = BASELINE_PCT - 4;

/** Uzak siluetlerin oturduğu ufuk. Zeminin biraz üstünde — araya boşluk girmez. */
export const HORIZON_PCT = GROUND_TOP_PCT - 20;
