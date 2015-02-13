MIN_SV_LENGTH = 50
OVERLAP_RATIO = 0.5
WIGGLE = 100
INS_WIGGLE = 100

# For generating candidate intervals for insertion assembly
MIN_SUPPORT = 5
MIN_SUPPORT_FRAC = 0.1
MAX_INTERVALS = 10000
SC_PAD = 500
SC_MIN_SOFT_CLIP = 20
SC_MAX_SOFT_CLIP = 50
SC_MIN_AVG_BASE_QUAL = 20
SC_MIN_MAPQ = 5

ISIZE_MIN = 250
ISIZE_MAX = 450

# For running SPAdes
SPADES_TIMEOUT = 300 # in seconds
SPADES_PAD = 500
SPADES_MAX_INTERVAL_SIZE = 50000

# For running AGE
AGE_TIMEOUT = 300 # in seconds
AGE_MIN_CONTIG_LENGTH = 200
AGE_PAD = 500
AGE_MAX_REGION_LENGTH = 50000
