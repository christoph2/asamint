
#if !defined(__REKORDER_HPP)
#define __REKORDER_HPP


#include <algorithm>
#include <cassert>
#include <cstdio>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <system_error>
#include <vector>

#include <lz4.h>
#include <mio/mmap.hpp>

void allocate_file(const std::string& path, const int size)
{
    std::ofstream file(path);
    std::string s(size, '0');
    file << s;
}

int handle_error(const std::error_code& error)
{
    const auto& errmsg = error.message();

    std::printf("error mapping file: %s, exiting...\n", errmsg.c_str());
    return error.value();
}

class XcpLogFileWriter {
public:
    XcpLogFileWriter() = delete;

    explicit XcpLogFileWriter(const std::string& file_name) {
        allocate_file(file_name, 155);

        std::error_code error;
        m_file = mio::make_mmap_sink(file_name, 0, mio::map_entire_file, error);

        if (error) {
            handle_error(error);
        }

    }

    ~XcpLogFileWriter() {

    }

private:
    mio::mmap_sink m_file; 
};

class XcpLogFileReader {
public:

    XcpLogFileReader() = delete;

    explicit XcpLogFileReader(const std::string& file_name) {
        allocate_file(file_name, 155);

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

