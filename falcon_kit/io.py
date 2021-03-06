


from pypeflow.io import (
        syscall, capture, cd,
        mkdirs, symlink, rm, touch, filesize, exists_and_not_empty) # needed?
import contextlib
import io
import logging
import os
import pprint
import sys

if sys.version_info >= (3, 0):
    NativeIO = io.StringIO
else:
    NativeIO = io.BytesIO

LOG = logging.getLogger()


def log(*msgs):
    LOG.debug(' '.join(repr(m) for m in msgs))


def eng(number):
    return '{:.1f}MB'.format(number / 2**20)


class Percenter(object):
    """Report progress by golden exponential.

    Usage:
        counter = Percenter('mystruct', total_len(mystruct))

        for rec in mystruct:
            counter(len(rec))
    """
    def __init__(self, name, total, log=LOG.info, units='units'):
        if sys.maxsize == total:
            log('Counting {} from "{}"'.format(units, name))
        else:
            log('Counting {:,d} {} from\n  "{}"'.format(total, units, name))
        self.total = total
        self.log = log
        self.name = name
        self.units = units
        self.call = 0
        self.count = 0
        self.next_count = 0
        self.a = 1 # double each time
    def __call__(self, more, label=''):
        self.call += 1
        self.count += more
        if self.next_count <= self.count:
            self.a = 2 * self.a
            self.a = max(self.a, more)
            self.a = min(self.a, (self.total-self.count), round(self.total/10.0))
            self.next_count = self.count + self.a
            if self.total == sys.maxsize:
                msg = '{:>10} count={:15,d} {}'.format(
                    '#{:,d}'.format(self.call), self.count, label)
            else:
                msg = '{:>10} count={:15,d} {:6.02f}% {}'.format(
                    '#{:,d}'.format(self.call), self.count, 100.0*self.count/self.total, label)
            self.log(msg)
    def finish(self):
        self.log('Counted {:,d} {} in {} calls from:\n  "{}"'.format(
            self.count, self.units, self.call, self.name))


def FilePercenter(fn, log=LOG.info):
    if '-' == fn or not fn:
        size = sys.maxsize
    else:
        size = filesize(fn)
        if fn.endswith('.dexta'):
            size = size * 4
        elif fn.endswith('.gz'):
            size = sys.maxsize # probably 2.8x to 3.2x, but we are not sure, and higher is better than lower
            # https://stackoverflow.com/a/22348071
            # https://jira.pacificbiosciences.com/browse/TAG-2836
    return Percenter(fn, size, log, units='bytes')

@contextlib.contextmanager
def open_progress(fn, mode='r', log=LOG.info):
    """
    Usage:
        with open_progress('foo', log=LOG.info) as stream:
            for line in stream:
                use(line)

    That will log progress lines.
    """
    def get_iter(stream, progress):
        for line in stream:
            progress(len(line))
            yield line

    fp = FilePercenter(fn, log=log)
    with open(fn, mode=mode) as stream:
        yield get_iter(stream, fp)
    fp.finish()


def read_as_msgpack(bytestream, log=log):
    import msgpack
    content = bytestream.read()
    log('  Read {} as msgpack'.format(eng(len(content))))
    return msgpack.unpackb(content, raw=False,
            max_map_len=2**25,
            max_array_len=2**25,
    )


def read_as_json(bytestream, log=log):
    import json
    content = bytestream.read().decode('ascii')
    log('  Read {} as json'.format(eng(len(content))))
    return json.loads(content)


def write_as_msgpack(bytestream, val, log=log):
    import msgpack
    content = msgpack.packb(val)
    # msgpack is not sorted like JSON because OrderedDict can be preserved anyway.
    log('  Serialized to {} as msgpack'.format(eng(len(content))))
    bytestream.write(content)


def write_as_json(bytestream, val, log=log):
    import json
    content = json.dumps(val, sort_keys=True, indent=2, separators=(',', ': ')).encode('ascii')
    log('  Serialized to {} as json'.format(eng(len(content))))
    bytestream.write(content)


def deserialize(fn, log=log):
    log('Deserializing from {!r}'.format(fn))
    with open(fn, 'rb') as ifs:
        log('  Opened for read: {!r}'.format(fn))
        if fn.endswith('.msgpack'):
            val = read_as_msgpack(ifs, log=log)
        elif fn.endswith('.json'):
            val = read_as_json(ifs, log=log)
        else:
            raise Exception('Unknown extension for {!r}'.format(fn))
    log('  Deserialized {} records'.format(len(val)))
    return val


def serialize(fn, val, only_if_needed=False, log=log):
    """Assume dirname exists.
    """
    log('Serializing {} records'.format(len(val)))
    mkdirs(os.path.dirname(fn))
    ofs = io.BytesIO()
    if fn.endswith('.msgpack'):
        write_as_msgpack(ofs, val, log=log)
    elif fn.endswith('.json'):
        write_as_json(ofs, val, log=log)
        ofs.write(b'\n') # for vim
    else:
        raise Exception('Unknown extension for {!r}'.format(fn))
    content = ofs.getvalue()
    if only_if_needed and os.path.exists(fn):
        with open(fn, 'rb') as ifs:
            current = ifs.read()
        if current == content:
            return
    with open(fn, 'wb') as ofs:
        log('  Opened for write: {!r}'.format(fn))
        ofs.write(content)


def yield_abspath_from_fofn(fofn_fn):
    """Yield each filename.
    Relative paths are resolved from the FOFN directory.
    'fofn_fn' can be .fofn, .json, .msgpack
    """
    try:
        fns = deserialize(fofn_fn)
    except:
        #LOG('las fofn {!r} does not seem to be JSON; try to switch, so we can detect truncated files.'.format(fofn_fn))
        fns = open(fofn_fn).read().strip().split()
    try:
        basedir = os.path.dirname(fofn_fn)
        for fn in fns:
            if not os.path.isabs(fn):
                fn = os.path.abspath(os.path.join(basedir, fn))
            yield fn
    except Exception:
        LOG.error('Problem resolving paths in FOFN {!r}'.format(fofn_fn))
        raise


def rmdirs(*dirnames):
    for d in dirnames:
        assert os.path.normpath(d.strip()) not in ['.', '', '/']
    syscall('rm -rf {}'.format(' '.join(dirnames)))

def rmdir(d):
    rmdirs(d)

def rm_force(*fns):
    for fn in fns:
        if os.path.exists(fn):
            os.unlink(fn)
