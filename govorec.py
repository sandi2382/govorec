import sys
import math
import os
import time

import numpy
from scipy.fftpack import dct, fft
from scipy.io import wavfile
from numpy.lib.stride_tricks import as_strided
from scipy.cluster import vq

FRAME_SIZE = 1024
STEP = int(FRAME_SIZE * 3 / 4)
NUM_COEFFICIENTS = 41
CODEBOOK_SIZE = 128
CODEBOOK_FN = 'codebook.npy'
DATADIR = os.path.abspath(os.path.dirname(__file__))

def freqToMel(freq):
    return 1127.01048 * math.log(1 + freq / 700.0)

def melToFreq(mel):
    return 700 * (math.exp(freq / 1127.01048 - 1))

def melFilterBank(blockSize, numCoefficients=13, minHz=0.0, maxHz=24000.0, sampleRate=48000):
    numBands = int(numCoefficients)
    maxMel = int(freqToMel(maxHz))
    minMel = int(freqToMel(minHz))

    # Create a matrix for triangular filters, one row per filter
    filterMatrix = numpy.zeros((numBands, blockSize))

    melRange = numpy.array(xrange(numBands + 2))

    melCenterFilters = melRange * (maxMel - minMel) / (numBands + 1) + minMel
    # each array index represent the center of each triangular filter
    aux = numpy.log(1 + 1000.0 / 700.0) / 1000.0
    aux = (numpy.exp(melCenterFilters * aux) - 1) / sampleRate
    aux = 0.5 + 700 * blockSize * aux
    aux = numpy.floor(aux)  # Arredonda pra baixo
    centerIndex = numpy.array(aux, int)  # Get int values
    
    for i in xrange(numBands):
        start, centre, end = centerIndex[i:i + 3]
        k1 = numpy.float32(centre - start)
        k2 = numpy.float32(end - centre)
        up = (numpy.array(xrange(start, centre)) - start) / k1
        down = (end - numpy.array(xrange(centre, end))) / k2
        filterMatrix[i][start:centre] = up
        filterMatrix[i][centre:end] = down

    return filterMatrix.transpose()

def oneMfcc(sampleRate, blockSize, signal, filterBank):
    complexSpectrum = fft(signal)
    powerSpectrum = abs(complexSpectrum) ** 2
    filteredSpectrum = numpy.dot(powerSpectrum, filterBank)
    logSpectrum = numpy.log(filteredSpectrum)
    dctSpectrum = dct(logSpectrum, type=2)  # MFCC :)
    return dctSpectrum

def printMelFilters():
    "draw a graph of mel filters"
    fb = melFilterBank(4096, numCoefficients=13)
    import pylab
    freq = numpy.array([i*24000.0/2048 for i in xrange(2048)])
    print fb.shape
    pylab.plot(freq, fb[:][0:2048])
    pylab.xlabel("Frekvenca [Hz]")
    pylab.ylabel("Odziv")
    pylab.show()

def run_mfcc(sampleRate, signal, frame_size, step, numCoefficients):
    #print 'division by step', signal.size % step
    num_frames = (signal.size - frame_size) / step + 1
    window = numpy.hamming(frame_size)

    frames = as_strided(signal, shape=(num_frames, frame_size), strides=(step*signal.itemsize, signal.itemsize))
    filterBank = melFilterBank(frame_size, numCoefficients=numCoefficients)

    resultdata = numpy.ones(num_frames * (numCoefficients-1))* -100
    mfcc = resultdata.reshape(num_frames, (numCoefficients-1))

    for num, frame in enumerate(frames):
        #if num % int(sampleRate / 20) == 0:
            #print '%.2f %%' % (num * 100.0 / num_frames)
        windowed_frame = frame * window
        m = oneMfcc(sampleRate, frame_size, windowed_frame, filterBank=filterBank)
        if not numpy.isnan(numpy.sum(m)):
            mfcc[num] = m[1:]
        else:
            #print 'nan!'
            pass
    return mfcc

def process_one_speaker(dirname):
    def getfile(x):
        return os.path.join(dirname, x)
    
    mfcc_results = []
    for wav in sorted(os.listdir(dirname)):
        if not wav.endswith('.wav'):
            continue
        print 'Reading', getfile(wav)
        sampleRate, signal = wavfile.read(getfile(wav))
        onemfcc = run_mfcc(sampleRate, signal, FRAME_SIZE, STEP, NUM_COEFFICIENTS)
        mfcc_results.append(onemfcc)

    mfcc_data = numpy.vstack(mfcc_results)
    print 'Learning from %d vectors.' % (mfcc_data.shape[0],)

    whitened = vq.whiten(mfcc_data)
    t1 = time.time()
    codebook = vq.kmeans(whitened, CODEBOOK_SIZE)
    t2 = time.time()
    print 'Generated codebook, took %.2fs' % (t2-t1,)
    f = open(getfile(CODEBOOK_FN), 'wb')
    numpy.save(f, codebook)
    f.close()

def cosine_distance(u, v):
    """
    Returns the cosine of the angle between vectors v and u. This is equal to
    u.v / |u||v|.
    """
    return numpy.dot(u, v) / (math.sqrt(numpy.dot(u, u)) * math.sqrt(numpy.dot(v, v)))

def recognize(wavfn):
    samplerate, w = wavfile.read(open(wavfn))
    mfcc = run_mfcc(samplerate, w, FRAME_SIZE, STEP, NUM_COEFFICIENTS)
    sample_length = mfcc.shape[0]
    whitened = vq.whiten(mfcc)
    
    def getfile(x):
        return os.path.join(DATADIR, x)
    
    sq_sum_candidates = []
    cos_sim_candidates = []
    for dirname in os.listdir(DATADIR):
        codebook_fn = os.path.join(DATADIR, dirname, CODEBOOK_FN)
        if not os.path.isfile(codebook_fn):
            continue
        codebook, dist_1 = numpy.load(open(codebook_fn, 'rb'))
        code, dist = vq.vq(whitened, codebook)
        sq_sum_candidates.append((sum(dist*dist)/sample_length, dirname))
        cos_dist = []
        for c, d, w in zip(code, dist, whitened):
            cdist = cosine_distance(codebook[c], w)
            cos_dist.append(cdist)
        cdista = numpy.array(cos_dist)
        cos_sim_candidates.append((sum(cdista)/sample_length, dirname))
    
    #print 'Order by square-sum error ascending:'
    #for score, person in sorted(sq_sum_candidates):
        #print '\t', score, person

    print 'Cosine similarity'
    for score, person in sorted(cos_sim_candidates, reverse=True):
        print '\t', score, person
    

if __name__ == "__main__":
    me = sys.argv[0]
    usage = """
    %s learn person_wavdir
    %s recognize file.wav
    """ % (me, me)
    try:
        fn = sys.argv[2]
    except IndexError:
        print usage
        sys.exit(1)

    if sys.argv[1] == "learn":
        process_one_speaker(fn)
    elif sys.argv[1] == "recognize":
        recognize(fn)
    else:
        print usage
        sys.exit(1)
