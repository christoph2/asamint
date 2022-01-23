
#include <stdint.h>


// #define DLL_EXPORT __declspec(dllexport) __cdecl

#define XcpSkExtFncAck                          (0)
#define XcpSkExtFncErrPrivilegeNotAvailable     (1)
#define XcpSkExtFncErrInvalidSeedLength         (2)
#define XcpSkExtFncErrUnsufficientKeyLength     (3)

#define RESOURCE_CALPAG                         (0x01)
#define RESOURCE_DAQ                            (0x04)
#define RESOURCE_STIM                           (0x08)
#define RESOURCE_PGM                            (0x10)

#define INITIAL_VALUE                           (0xBC)


uint32_t XCP_ComputeKeyFromSeed (uint8_t resource, uint8_t seedLen, uint8_t const *seedPtr, uint8_t * keyLenPtr, uint8_t * keyPtr)
{
    uint32_t result = XcpSkExtFncAck;
    uint8_t idx;

    keyPtr[0] = (seedPtr[0] + seedPtr[3]) ^ INITIAL_VALUE;
    for (idx = 1; idx < seedLen; idx++) {
        keyPtr[idx] = seedPtr[idx] ^ keyPtr[idx - 1];
    }
    *keyLenPtr = seedLen;
    result = XcpSkExtFncAck;

    return result;
}


uint32_t XCP_GetAvailablePrivileges(uint8_t * resourcePtr)
{
  *resourcePtr = RESOURCE_CALPAG | RESOURCE_DAQ | RESOURCE_PGM | RESOURCE_STIM;

  return XcpSkExtFncAck;
}
