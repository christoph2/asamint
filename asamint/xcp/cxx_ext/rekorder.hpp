
#if !defined(__REKORDER_HPP)
#define __REKORDER_HPP


#include <algorithm>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <memory.h>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <system_error>
#include <vector>

#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>

#include <lz4.h>
#include <mio/mmap.hpp>

#include <endian.hpp>

//#include <mio/mio.hpp>

#define XMR_FILE_EXTENSION      ".xmraw"    // XCP measurement / raw data.

#define XMR_MAGIC               "ASAMINT::XCP_RAW"

#define XMR_VERSION             (0x100)     // Current format version.

#define XMR_HEADER_FILL_BYTES   (10)
#define XMR_UNUSED_BYTES_VALUE  (0xcc)

/*
 *
 * Conventions: - Numerical quantities are stored LSB first (Little Endian). - Unused bytes are set to 0xCC.
 *
 */

#if 0
FILE_HEADER_STRUCT = struct.Struct("<{:d}sHHHLLLL".format(len(MAGIC)))
FileHeader = namedtuple("FileHeader", "magic hdr_size version options num_containers record_count size_compressed size_uncompressed") #

CONTAINER_HEADER_STRUCT = struct.Struct("<LLL")
ContainerHeader = namedtuple("ContainerHeader", "record_count size_compressed size_uncompressed")

DAQ_RECORD_STRUCT = struct.Struct("<BHdL")
DAQRecord = namedtuple("DAQRecord", "category counter timestamp payload")
#endif

#pragma pack(push, 1)
struct XmrFileHeader {
    char magic[sizeof(XMR_MAGIC) - 1];
    uint16_t hdr_size;
    uint16_t version;
    uint16_t options;
    uint32_t num_containers;
    uint32_t record_count;
    uint32_t size_compressed;
    uint32_t size_uncompressed;
    char filler[XMR_HEADER_FILL_BYTES];
};

static_assert(sizeof(XmrFileHeader) == 48, "XmrFileHeader must be 48 bytes.");

struct XmrContainerHeader {
    uint32_t record_count;
    uint32_t size_compressed;
    uint32_t size_uncompressed;
};

struct XmrDaqRecord {
    uint8_t category;
    uint16_t counter;
    double timestamp;
    std::vector<char> payload;
};
#pragma pack(pop)

int handle_error(const std::error_code& error)
{
    const auto& errmsg = error.message();

    std::printf("error mapping file: %s, exiting...\n", errmsg.c_str());
    return error.value();
}

class XcpFrame {
public:
    template <std::size_t N> using frame_t = std::array<char, N>;
    const std::size_t displacement = (2 * sizeof(uint16_t)) + sizeof(double); // Consider counter, seq_no, and timestamp.

    template <std::size_t N> XcpFrame<N>() {
        frame = new frame_t<N + displacement>;
    }

    uint16_t counter() const {

    }

    uint16 seq_no() const {

    }

    double timestamp() const {

    }

    ~XcpFrame() noexcept {
        delete frame;
    }

private:
    frame_t * frame;
};

class XcpLogFileWriter {
public:
    XcpLogFileWriter() = delete;

    explicit XcpLogFileWriter(const std::string& file_name, size_t prealloc = 10, size_t chunk_size = 1024, size_t compression_level = 9) {
        std::error_code error;

		preallocate_sparse_file(file_name, 4096 * 32);
        m_file = new mio::mmap_sink(file_name, 0, mio::map_entire_file);
        m_container_header_offset = sizeof(XmrFileHeader);
        m_current_offset = m_container_header_offset + sizeof(XmrContainerHeader);
        m_chunk_size = chunk_size * 1024;
        m_page_size = mio::page_size();

        write_header(XMR_VERSION, 0x0000, m_num_containers, m_total_record_count, m_total_size_compressed, m_total_size_uncompressed);


#if 0
        try:
            self._of = open("{}{}".format(file_name, FILE_EXTENSION), "w+b")
        except Exception as e:
            raise
        else:
            self._of.truncate(1024 * 1024 * prealloc)   # Create sparse file (hopefully).
            self._mapping = mmap.mmap(self._of.fileno(), 0)
        self.intermediate_storage = []
        self.compression_level = compression_level
        self.prealloc = prealloc
#endif

        m_file->sync(error);

    }

    ~XcpLogFileWriter() noexcept {
        m_file->unmap();
        delete m_file;
    }

    void add_xcp_frames(const std::vector<XcpFrame>& frames) {
        for (auto& frame: frames) {
            add_xcp_frame(frame);
        }
    }

protected:

    void add_xcp_frame(const XcpFrame& frame) {

    }

    bool file_exists(const std::string& path) const {
        return ::access(path.c_str(), F_OK) == 0;
    }

    void preallocate_sparse_file(const std::string& path, const int size) {
		int fd = ::open(path.c_str(), O_CREAT | O_RDWR | O_TRUNC, 0764);
		if (fd == -1) {
			//
		}

		::ftruncate(fd, size);
		::close(fd);
    }


    void write_header(uint16_t version, uint16_t options, uint32_t num_containers, uint32_t record_count,
            uint32_t size_compressed, uint32_t size_uncompressed) const {
        auto offset = 0;
        auto data_ptr = m_file->data();

        ::memcpy(data_ptr, XMR_MAGIC, sizeof(XMR_MAGIC) - 1);
        offset += sizeof(XMR_MAGIC) - 1;
        endian::write_le<2>(sizeof(XmrFileHeader), data_ptr + offset);
        offset += 2;
        endian::write_le<2>(version, data_ptr + offset);
        offset += 2;
        endian::write_le<2>(options, data_ptr + offset);
        offset += 2;
        endian::write_le<4>(num_containers, data_ptr + offset);
        offset += 4;
        endian::write_le<4>(record_count, data_ptr + offset);
        offset += 4;
        endian::write_le<4>(size_compressed, data_ptr + offset);
        offset += 4;
        endian::write_le<4>(size_uncompressed, data_ptr + offset);
        offset += 4;
        ::memset(data_ptr + offset, XMR_UNUSED_BYTES_VALUE, XMR_HEADER_FILL_BYTES);
    }

private:
    mio::mmap_sink * m_file = nullptr;
    //mio::mmap_sink m_file;
    //shared_mmap_sink m_file;
    uint64_t m_container_header_offset = 0ULL;
    uint64_t m_current_offset = 0ULL;
    uint64_t m_total_size_uncompressed = 0ULL;
    uint64_t m_total_size_compressed = 0ULL;
    uint64_t m_container_size_uncompressed = 0ULL;
    uint64_t m_container_size_compressed = 0ULL;
    uint32_t m_total_record_count = 0UL;
    uint32_t m_chunk_size = 0UL;
    uint32_t m_num_containers = 0UL;
    uint32_t m_page_size;
};


class XcpLogFileReader {
public:

    XcpLogFileReader() = delete;

    explicit XcpLogFileReader(const std::string& file_name) {
        std::error_code error;
        mio::mmap_sink rw_mmap = mio::make_mmap_sink(file_name, 0, mio::map_entire_file, error);

        if (error) {
            handle_error(error);
        }

        std::fill(rw_mmap.begin(), rw_mmap.end(), 'a');

        // Or manually iterate through the mapped region just as if it were any other
        // container, and change each byte's value (since this is a read-write mapping).

        for (auto& b : rw_mmap) {
             b += 10;
        }

        const int answer_index = rw_mmap.size() / 2;
        rw_mmap[answer_index] = 42;

        rw_mmap.sync(error);
        if (error) {
            handle_error(error);
        }

        rw_mmap.unmap();

#if 0
        mio::mmap_source ro_mmap;
        ro_mmap.map(file_name, error);
        if (error) {
            handle_error(error);
        }

        const int the_answer_to_everything = ro_mmap[answer_index];
        assert(the_answer_to_everything == 42);
#endif

//        m_file = new std::fstream(file_name, std::fstream::out | std::fstream::binary | std::fstream::trunc);
    }

    ~XcpLogFileReader() {
        m_file->close();
    }

protected:

private:
    std::fstream * m_file;
    bool is_closed { true };

};

#if 0

class XcpLogFileReader:
    def __init__(self, file_name):
        self._is_closed = True
        try:
            self._log_file = open("{}{}".format(file_name, FILE_EXTENSION), "r+b")
        except Exception as e:
            raise
        else:
            self._mapping = mmap.mmap(self._log_file.fileno(), 0)

        self._is_closed = False
        magic, _, _, _, self.num_containers, self.total_record_count, self.total_size_compressed, self.total_size_uncompressed = (
            FILE_HEADER_STRUCT.unpack(self.get(0, FILE_HEADER_STRUCT.size))
        )
        if magic != MAGIC:
            raise XcpLogFileParseError("Invalid file magic: '{}'.".format(magic))

    def __del__(self):
        if not self._is_closed:
            self.close()

    @property
    def frames(self):
        offset = FILE_HEADER_STRUCT.size
        for _ in range(self.num_containers):
            record_count, size_compressed, size_uncompressed = CONTAINER_HEADER_STRUCT.unpack(self.get(offset, CONTAINER_HEADER_STRUCT.size))
            offset += CONTAINER_HEADER_STRUCT.size
            uncompressed_data = memoryview(lz4block.decompress(self.get(offset, size_compressed)))
            frame_offset = 0
            for _ in range(record_count):
                category, counter, timestamp, frame_length = DAQ_RECORD_STRUCT.unpack(
                    uncompressed_data[frame_offset : frame_offset + DAQ_RECORD_STRUCT.size]
                )
                frame_offset += DAQ_RECORD_STRUCT.size
                frame_data = uncompressed_data[frame_offset : frame_offset + frame_length] # .tobytes()
                frame_offset += len(frame_data)
                frame = DAQRecord(category, counter, timestamp, frame_data)
                yield frame
            offset += size_compressed

    def get(self, address: int, length: int):
        return self._mapping[address : address + length]

    def close(self):
        if hasattr(self, "self._mapping"):
            self._mapping.close()
        self._log_file.close()
        self._is_closed = True

    @property
    def compression_ratio(self):
        if self.total_size_compressed:
            return self.total_size_uncompressed / self.total_size_compressed
#endif

#endif // __REKORDER_HPP

