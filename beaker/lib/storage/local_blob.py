from pyteal import (
    Txn,
    App,
    Bytes,
    Concat,
    Expr,
    Extract,
    For,
    GetByte,
    If,
    Int,
    Len,
    Or,
    ScratchVar,
    Seq,
    SetByte,
    Subroutine,
    Substring,
    TealType,
)
from beaker.lib.storage.blob import BLOB_PAGE_SIZE, EMPTY_PAGE, Blob


class LocalBlob(Blob):
    """
    Blob is a class holding static methods to work with the local storage of an account as a binary large object

    The `zero` method must be called on an account on opt in and the schema of the local storage should be 16 bytes
    """

    def __init__(self, /, *, max_keys: int = None, keys: list[int] = None):
        super().__init__(16, max_keys=max_keys, keys=keys)

    def zero(self, acct: Expr = Txn.sender()) -> Expr:
        """
        initializes local state of an account to all zero bytes

        This allows us to be lazy later and _assume_ all the strings are the same size

        """

        @Subroutine(TealType.none)
        def _impl(acct):
            return Seq(
                *[App.localPut(acct, Bytes(bk), EMPTY_PAGE) for bk in self.byte_keys]
            )

        return _impl(acct)

    def get_byte(self, idx, acct: Expr = Txn.sender()):
        """
        Get a single byte from local storage of an account by index
        """

        @Subroutine(TealType.uint64)
        def _impl(acct, idx):
            return GetByte(
                App.localGet(acct, self._key(self._key_idx(idx))),
                self._offset_for_idx(idx),
            )

        return _impl(acct, idx)

    def set_byte(self, idx, byte, acct: Expr = Txn.sender()):
        """
        Set a single byte from local storage of an account by index
        """

        @Subroutine(TealType.none)
        def _impl(acct, idx, byte):
            return Seq(
                (key := ScratchVar()).store(self._key(self._key_idx(idx))),
                App.localPut(
                    acct,
                    key.load(),
                    SetByte(
                        App.localGet(acct, key.load()), self._offset_for_idx(idx), byte
                    ),
                ),
            )

        return _impl(acct, idx, byte)

    def read(self, bstart, bend, acct: Expr = Txn.sender()) -> Expr:
        """
        read bytes between bstart and bend from local storage of an account by index
        """

        @Subroutine(TealType.bytes)
        def _impl(acct, bstart, bend):
            start_key_idx = self._key_idx(bstart)
            start_offset = self._offset_for_idx(bstart)

            stop_key_idx = self._key_idx(bend)
            stop_offset = self._offset_for_idx(bend)

            key_idx = ScratchVar()
            buff = ScratchVar()

            start = ScratchVar()
            stop = ScratchVar()

            init = key_idx.store(start_key_idx)
            cond = key_idx.load() <= stop_key_idx
            incr = key_idx.store(key_idx.load() + Int(1))

            return Seq(
                buff.store(Bytes("")),
                For(init, cond, incr).Do(
                    Seq(
                        start.store(
                            If(key_idx.load() == start_key_idx, start_offset, Int(0))
                        ),
                        stop.store(
                            If(
                                key_idx.load() == stop_key_idx,
                                stop_offset,
                                BLOB_PAGE_SIZE,
                            )
                        ),
                        buff.store(
                            Concat(
                                buff.load(),
                                Substring(
                                    App.localGet(acct, self._key(key_idx.load())),
                                    start.load(),
                                    stop.load(),
                                ),
                            )
                        ),
                    )
                ),
                buff.load(),
            )

        return _impl(acct, bstart, bend)

    def write(self, bstart, buff, acct: Expr = Txn.sender()) -> Expr:
        """
        write bytes between bstart and len(buff) to local storage of an account
        """

        @Subroutine(TealType.none)
        def _impl(acct, bstart, buff):

            start_key_idx = self._key_idx(bstart)
            start_offset = self._offset_for_idx(bstart)

            stop_key_idx = self._key_idx(bstart + Len(buff))
            stop_offset = self._offset_for_idx(bstart + Len(buff))

            key_idx = ScratchVar()
            start = ScratchVar()
            stop = ScratchVar()
            written = ScratchVar()

            init = key_idx.store(start_key_idx)
            cond = key_idx.load() <= stop_key_idx
            incr = key_idx.store(key_idx.load() + Int(1))

            delta = ScratchVar()

            return Seq(
                written.store(Int(0)),
                For(init, cond, incr).Do(
                    Seq(
                        start.store(
                            If(key_idx.load() == start_key_idx, start_offset, Int(0))
                        ),
                        stop.store(
                            If(
                                key_idx.load() == stop_key_idx,
                                stop_offset,
                                BLOB_PAGE_SIZE,
                            )
                        ),
                        App.localPut(
                            acct,
                            self._key(key_idx.load()),
                            If(
                                Or(
                                    stop.load() != BLOB_PAGE_SIZE,
                                    start.load() != Int(0),
                                )
                            )  # Its a partial write
                            .Then(
                                Seq(
                                    delta.store(stop.load() - start.load()),
                                    Concat(
                                        Substring(
                                            App.localGet(
                                                acct, self._key(key_idx.load())
                                            ),
                                            Int(0),
                                            start.load(),
                                        ),
                                        Extract(buff, written.load(), delta.load()),
                                        Substring(
                                            App.localGet(
                                                acct, self._key(key_idx.load())
                                            ),
                                            stop.load(),
                                            BLOB_PAGE_SIZE,
                                        ),
                                    ),
                                )
                            )
                            .Else(
                                Seq(
                                    delta.store(BLOB_PAGE_SIZE),
                                    Extract(buff, written.load(), BLOB_PAGE_SIZE),
                                )
                            ),
                        ),
                        written.store(written.load() + delta.load()),
                    )
                ),
            )

        return _impl(acct, bstart, buff)
