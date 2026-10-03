import ZstdC

// Calling the renamed function verifies API notes are actually imported.
precondition(zstdDefaultCompressionLevel() == 3)
precondition(ZSTD_versionNumber() == 10507)
let context: OpaquePointer? = ZSTD_createCCtx()
precondition(context != nil)
precondition(ZSTD_isError(ZSTD_CCtx_setParameter(context, ZSTD_c_nbWorkers, 2)) == 0)
precondition(ZSTD_isError(ZSTD_freeCCtx(context)) == 0)
print("Swift 6 module import, API notes, nullable context, multithreading: passed")
