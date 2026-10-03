#include <zstd.h>
#include <zdict.h>
#include <ZstdSupport.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    const char input[] = "Zstandard XCFramework native round-trip verification.";
    unsigned char compressed[256], decoded[sizeof(input)];
    ZSTD_CCtx *context = ZSTD_createCCtx();
    if (!context || ZSTD_versionNumber() != 10507) return 1;
    if (ZSTD_isError(ZSTD_CCtx_setParameter(context, ZSTD_c_nbWorkers, 2))) return 2;
    if (ZSTD_isError(ZSTD_CCtx_setParameter(context, ZSTD_c_checksumFlag, 1))) return 3;
    size_t size = ZSTD_compress2(context, compressed, sizeof(compressed), input, sizeof(input));
    if (ZSTD_isError(size)) return 4;
    unsigned long long window = 0;
    if (ZstdC_frameWindowSize(compressed, size, &window) != 0 || window == 0) return 8;
    if (ZstdC_frameWindowSize(compressed, 1, &window) == 0) return 9;
    const unsigned char skippable[] = {0x50, 0x2a, 0x4d, 0x18, 0, 0, 0, 0};
    if (ZstdC_frameWindowSize(skippable, sizeof(skippable), &window) != 0 || window != 0) return 10;
    const unsigned char invalid[] = {0, 0, 0, 0, 0, 0, 0, 0};
    if (!ZSTD_isError(ZstdC_frameWindowSize(invalid, sizeof(invalid), &window))) return 11;
    size_t result = ZSTD_decompress(decoded, sizeof(decoded), compressed, size);
    if (ZSTD_isError(result) || result != sizeof(input) || memcmp(input, decoded, result)) return 5;
    if (ZDICT_getDictID(input, sizeof(input)) != 0) return 6;
    if (ZSTD_isError(ZSTD_freeCCtx(context))) return 7;
    puts("C round trip, dictionary API, checksum, multithreading, frame window inspection: passed");
    return 0;
}
