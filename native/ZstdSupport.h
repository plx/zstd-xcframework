#ifndef HDXL_ZSTD_SUPPORT_H
#define HDXL_ZSTD_SUPPORT_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Inspects a standard or skippable frame header. Returns 0 for a complete
 * header, a positive required header length for incomplete input, or a zstd
 * error code. On success, writes the frame's declared window size (0 for
 * skippable frames). No unstable upstream structs cross this interface. */
size_t ZstdC_frameWindowSize(const void *source, size_t sourceSize,
                            unsigned long long *windowSize);

#ifdef __cplusplus
}
#endif

#endif
