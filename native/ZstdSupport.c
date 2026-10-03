/* This helper is built against the exact pinned zstd revision. Its small C ABI
 * insulates clients from changes to zstd's static-only frame-header struct. */
#define ZSTD_STATIC_LINKING_ONLY
#include "zstd.h"
#include "ZstdSupport.h"

size_t ZstdC_frameWindowSize(const void *source, size_t sourceSize,
                            unsigned long long *windowSize) {
  ZSTD_frameHeader header;
  size_t result = ZSTD_getFrameHeader(&header, source, sourceSize);
  if (result == 0) {
    *windowSize = header.windowSize;
  }
  return result;
}
