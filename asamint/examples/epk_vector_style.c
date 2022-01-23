
#define EPK_SECTION_NAME    "calflash_signature"
#define EPK_CONST_NAME      "EcuName V1.2.0 01.03.2012"


// GNU syntax.
__attribute__((section(EPK_SECTION_NAME))) const char epk[sizeof(EPK_CONST_NAME)] = EPK_CONST_NAME;


int main()
{
    return 0;
}
