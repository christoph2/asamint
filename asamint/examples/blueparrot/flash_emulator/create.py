from objutils import Image, Section, dump


NUM_PAGES = 32
PAGE_SIZE = 0x4000

INCREMENT = 0x1
START_VALUE = 0x10


def create_example_hexfile():
    sections = []
    for idx in range(NUM_PAGES):
        page = START_VALUE + (INCREMENT * idx)
        values = [page] * PAGE_SIZE  # Use page information also as value.
        sections.append(Section(start_address=page << 16, data=values))
    img = Image(sections)
    dump("srec", "paged_flash.s28", img)


create_example_hexfile()
