class ImageAdapter:
    pass


class HexFileAdapter(ImageAdapter):
    pass


class XcpAdapter(ImageAdapter):
    pass


class Image:

    def __init__(self, file_path) -> None:
        self.file_path = file_path
