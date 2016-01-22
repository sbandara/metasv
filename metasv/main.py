from collections import defaultdict
import shutil

from defaults import *
from vcf_utils import *
from sv_interval import SVInterval, get_gaps_file, interval_overlaps_interval_list, merge_intervals, merge_intervals_recursively
from pindel_reader import PindelReader
from breakdancer_reader import BreakDancerReader
from breakseq_reader import BreakSeqReader
from cnvnator_reader import CNVnatorReader
from generate_sv_intervals import parallel_generate_sc_intervals
from run_spades import run_spades_parallel
from run_age import run_age_parallel
from generate_final_vcf import convert_metasv_bed_to_vcf
from fasta_utils import get_contigs
from genotype import parallel_genotype_intervals
from _version import __version__

FORMAT = '%(levelname)s %(asctime)-15s %(name)-20s %(message)s'
logging.basicConfig(level=logging.INFO, format=FORMAT)
logger = logging.getLogger(__name__)


def create_dirs(dirlist):
    for dirname in dirlist:
        if not os.path.isdir(dirname):
            logger.info("Creating directory %s" % (dirname))
            os.makedirs(dirname)


def make_contig_whiteset(args, reference_contigs):
    contig_whitelist = set(args.chromosomes) if args.chromosomes else set([contig.name for contig in reference_contigs])
    if args.keep_standard_contigs:
        contig_whitelist &= set(
            [str(i) for i in xrange(1, 23)] + ["chr%d" % (i) for i in xrange(1, 23)] + ["X", "Y", "MT", "chrX", "chrY",
                                                                                        "chrM"])
    return contig_whitelist


def canonical_result_file(args):
    return os.path.join(args.outdir, "variants.vcf")


def run_metasv(args):
    logger.info("Running MetaSV %s" % __version__)
    logger.info("Arguments are " + str(args))
    
    # Check if there is work to do
    if not (args.pindel_vcf + args.breakdancer_vcf + args.breakseq_vcf + args.cnvnator_vcf +
            args.pindel_native + args.breakdancer_native + args.breakseq_native + args.cnvnator_native +
            args.manta_vcf + args.lumpy_vcf + args.cnvkit_vcf, args.wham_vcf):
        logger.warning("Nothing to merge since no SV file specified")

    # Simple check for arguments
    if not args.disable_assembly:
        if not args.spades:
            logger.error("Spades executable not specified")
            return os.EX_USAGE

        if not args.age:
            logger.error("AGE executable not specified")
            return os.EX_USAGE

    # Create the directories for working
    bedtools_tmpdir = os.path.join(args.workdir, "bedtools")
    create_dirs([args.workdir, args.outdir, bedtools_tmpdir])

    # Reference handling
    if not os.path.isfile(args.reference + ".fai"):
        logger.error("Reference file %s is not indexed" % (args.reference))
        return 1

    fasta_handle = pysam.Fastafile(args.reference) if os.path.isfile(args.reference) else None
    contigs = get_contigs(args.reference)
    include_intervals = sorted(
        [SVInterval(contig.name, 0, contig.length, contig.name, "include", length=contig.length) for contig in contigs])

    contig_whitelist = make_contig_whiteset(args, contigs)
    logger.info("Only SVs on the following contigs will be reported: %s" % (sorted(list(contig_whitelist))))

    # Load the intervals from different files
    vcf_name_list = [("CNVnator", args.cnvnator_vcf), ("Pindel", args.pindel_vcf),
                     ("BreakDancer", args.breakdancer_vcf),
                     ("BreakSeq", args.breakseq_vcf), ("HaplotypeCaller", args.gatk_vcf),
                     ("Lumpy", args.lumpy_vcf), ("Manta", args.manta_vcf), ("CNVkit", args.cnvkit_vcf),
                     ("WHAM", args.wham_vcf)]
    native_name_list = [("CNVnator", args.cnvnator_native, CNVnatorReader),
                        ("Pindel", args.pindel_native, PindelReader),
                        ("BreakSeq", args.breakseq_native, BreakSeqReader),
                        ("BreakDancer", args.breakdancer_native, BreakDancerReader)]

    tools = []
    intervals = {}
    sv_types = set()

    gap_intervals = []
    if args.filter_gaps:
        gaps = args.gaps if args.gaps else get_gaps_file(contig_whitelist)
        gap_intervals = sorted(load_gap_intervals(gaps))

    # Handles native input
    logger.info("Load native files")
    for toolname, nativename, svReader in native_name_list:
        # If no native file is given, ignore the tool
        if not nativename: continue

        tools.append(toolname)
        intervals[toolname] = defaultdict(list)

        for native_file in nativename:
            for record in svReader(native_file, svs_to_report=args.svs_to_report):
                interval = record.to_sv_interval()
                BD_min_inv_len = args.mean_read_length+4*args.isize_sd
                if toolname=="BreakDancer" and interval.sv_type == "INV" and  abs(interval.length)< BD_min_inv_len:
                    #Filter BreakDancer artifact INVs with size < readlength+4*isize_sd
                    continue

                if not interval:
                    # This is the case for SVs we want to skip
                    continue
                if not interval_overlaps_interval_list(interval, gap_intervals) and interval.chrom in contig_whitelist:
                    
                    # Check length
                    if interval.length < args.minsvlen and interval.sv_type not in  ["ITX", "CTX"]:
                        continue

                    # Set wiggle
                    if interval.sv_type not in ["ITX","CTX"]:
                        interval.wiggle = max(args.inswiggle if interval.sv_type == "INS" else 0, args.wiggle)
                    else:
                        interval.wiggle = TX_WIGGLE
                    
                    intervals[toolname][interval.sv_type].append(interval)
        sv_types |= set(intervals[toolname].keys())

    # Handles the VCF input cases, we will just deal with these cases
    logger.info("Load VCF files")
    for toolname, vcfname in vcf_name_list:
        # If no VCF is given, ignore the tool
        if not vcfname:
            continue

        tools.append(toolname)
        intervals[toolname] = {}

        vcf_list = []
        for vcffile in vcfname:
            if os.path.isdir(vcffile):
                logger.info("Will load from per-chromosome VCFs from directory %s for tool %s" % (vcffile, toolname))
                vcf_list += [os.path.join(vcffile, "%s.vcf.gz" % contig.name) for contig in contigs if
                             (not contig_whitelist or contig.name in contig_whitelist)]
            else:
                vcf_list.append(vcffile)

        for vcffile in vcf_list:
            load_intervals(vcffile, intervals[toolname], gap_intervals, include_intervals, toolname, contig_whitelist,
                           minsvlen=args.minsvlen, wiggle=args.wiggle, inswiggle=args.inswiggle,
                           svs_to_report=args.svs_to_report, maxsvlen=args.maxsvlen)
        sv_types |= set(intervals[toolname].keys())

    logger.info("SV types are %s" % (str(sv_types)))
    tool_merged_intervals = {}
    final_intervals = []

    # This will just output per-tool VCFs, no intra-tool merging is done yet
    if args.enable_per_tool_output:
        logger.info("Output per-tool VCFs")
        for toolname in intervals:
            tool_out = os.path.join(args.outdir, "%s.vcf" % (toolname.lower()))

            logger.info("Outputting single tool VCF for %s" % (str(toolname)))
            vcf_template_reader = vcf.Reader(open(os.path.join(mydir, "resources/template.vcf"), "r"))
            vcf_template_reader.samples = [args.sample]

            intervals_tool = []
            tool_out_fd = open(tool_out, "w")
            vcf_writer = vcf.Writer(tool_out_fd, vcf_template_reader)
            chr_intervals_tool = {contig.name: [] for contig in contigs}
            for sv_type in sv_types:
                if sv_type in intervals[toolname]:
                    intervals_tool.extend([copy.deepcopy(interval) for interval in intervals[toolname][sv_type]])
            for interval in intervals_tool:
                # Marghoob says that this is just to fill-in some metadata
                interval.do_validation(args.overlap_ratio)

                interval.fix_pos()
                chr_intervals_tool[interval.chrom].append(interval)

            for contig in contigs:
                chr_intervals_tool[contig.name].sort()
                for interval in chr_intervals_tool[contig.name]:
                    vcf_record = interval.to_vcf_record(fasta_handle, args.sample)
                    if vcf_record is not None:
                        vcf_writer.write_record(vcf_record)
            tool_out_fd.close()
            vcf_writer.close()
            logger.info("Indexing single tool VCF for %s" % (str(toolname)))
            pysam.tabix_index(tool_out, force=True, preset="vcf")

    # Do merging here
    logger.info("Do merging")
    for sv_type in sv_types:
        logger.info("Processing SVs of type %s" % sv_type)
        tool_merged_intervals[sv_type] = []

        # Do the intra-tool merging
        logger.info("Intra-tool Merging SVs of type %s" % sv_type)
        for tool in tools:
            logger.debug("Is %s in tool keys? %s" % (sv_type, str(intervals[tool].keys())))
            if sv_type not in intervals[tool]:
                logger.debug("%s not in tool %s" % (sv_type, tool))
                continue
            logger.info("First level merging for %s for tool %s" % (sv_type, tool))
            tool_merged_intervals[sv_type] += merge_intervals(intervals[tool][sv_type])

        # Do the inter-tool merging
        logger.info("Inter-tool Merging SVs of type %s" % sv_type)
        final_intervals.extend(merge_intervals_recursively(tool_merged_intervals[sv_type],args.overlap_ratio))

    final_chr_intervals = {contig.name: [] for contig in contigs}
    for interval in final_intervals:
        interval.do_validation(args.overlap_ratio)
        interval.fix_pos()
        if args.minsvlen <= interval.length <= args.maxsvlen or interval.sv_type in ["ITX", "CTX"]:
            final_chr_intervals[interval.chrom].append(interval)

    # This is the merged VCF without assembly, ok for deletions at this point
    logger.info("Output merged VCF without assembly ")
    vcf_template_reader = vcf.Reader(open(os.path.join(mydir, "resources/template.vcf"), "r"))
    vcf_template_reader.samples = [args.sample]
    preasm_vcf = os.path.join(args.workdir, "pre_asm.vcf")
    vcf_fd = open(preasm_vcf, "w")
    vcf_writer = vcf.Writer(vcf_fd, vcf_template_reader)

    final_stats = {}

    bed_intervals = []
    for contig in contigs:
        final_chr_intervals[contig.name].sort()
        for interval in final_chr_intervals[contig.name]:
            vcf_record = interval.to_vcf_record(fasta_handle)
            if vcf_record is not None:
                key = (interval.sv_type, "PASS" if interval.is_validated else "LowQual",
                       "PRECISE" if interval.is_precise else "IMPRECISE", tuple(sorted(list(interval.sources))))
                if key not in final_stats:
                    final_stats[key] = 0
                final_stats[key] += 1
                vcf_writer.write_record(vcf_record)
            bed_interval = interval.to_bed_interval(args.sample)
            if bed_interval is not None:
                bed_intervals.append(bed_interval)
    vcf_fd.close()
    vcf_writer.close()

    # Also save a BED file representation of the merged variants without assembly
    merged_bed = None
    if bed_intervals:
        merged_bed = os.path.join(args.workdir, "metasv.bed")
        pybedtools.BedTool(bed_intervals).saveas(merged_bed)

    for key in sorted(final_stats.keys()):
        logger.info(str(key) + ":" + str(final_stats[key]))

    final_vcf = canonical_result_file(args)

    # Run assembly here
    if args.assembly == ASM_DISABLE:
        shutil.copy(preasm_vcf, final_vcf)
        pysam.tabix_index(final_vcf, force=True, preset="vcf")
    else:
        # this does the improved assembly location finder with softclipped reads
        if args.boost_sc:
            logger.info("Generating Soft-Clipping intervals.")
            assembly_bed = parallel_generate_sc_intervals([args.bam.name], list(contig_whitelist), merged_bed,
                                                          args.workdir,
                                                          num_threads=args.num_threads,
                                                          min_support_ins=args.min_support_ins,
                                                          min_support_frac_ins=args.min_support_frac_ins,
                                                          max_intervals=args.max_ins_intervals, min_mapq=args.min_mapq,
                                                          min_avg_base_qual=args.min_avg_base_qual,
                                                          min_soft_clip=args.min_soft_clip,
                                                          max_nm=args.max_nm, min_matches=args.min_matches,
                                                          isize_mean=args.isize_mean, isize_sd=args.isize_sd,                                                        
                                                          svs_to_softclip=args.svs_to_softclip,
                                                          overlap_ratio=args.overlap_ratio,
                                                          mean_read_length=args.mean_read_length,
                                                          mean_read_coverage=args.mean_read_coverage, 
                                                          min_ins_cov_frac=args.min_ins_cov_frac,
                                                          max_ins_cov_frac=args.max_ins_cov_frac,
                                                          assembly_max_tools=args.assembly_max_tools)
        else:
            assembly_bed = merged_bed
        logger.info("Generated intervals for assembly in %s" % assembly_bed)

        if args.assembly == ASM_FULL:
            logger.info("Will run assembly now")
            genotyped_bed = asm_sc_intervals(bed=assembly_bed, bam_file=args.bam.name, reference=args.reference,
                                             sample=args.sample, contigs=list(contig_whitelist),
                                             padding=args.assembly_pad, workdir=args.workdir, spades_exec=args.spades,
                                             sp_opts=args, age_exec=args.age, age_opts=args, gt_opts=args)
            logger.info("Output final VCF file")
            convert_metasv_bed_to_vcf(bedfiles=[genotyped_bed], vcf_out=final_vcf, workdir=args.workdir,
                                      sample=args.sample, reference=args.reference, pass_calls=False)

    logger.info("Clean up pybedtools")
    pybedtools.cleanup(remove_all=True)
    logger.info("All Done!")
    return os.EX_OK


def asm_sc_intervals(bed=None, bam_file=None, reference=None, sample=None, contigs=None, padding=None, workdir=None,
                     spades_exec=None, sp_opts=None, age_exec=None, age_opts=None, gt_opts=None, slicing=None):
    spades_tmpdir = os.path.join(workdir, "spades")
    age_tmpdir = os.path.join(workdir, "age")
    gt_tmpdir = os.path.join(workdir, "genotyping")
    create_dirs([spades_tmpdir, age_tmpdir, gt_tmpdir])
    assembled_fasta, ignored_bed = run_spades_parallel(bam=bam_file, spades=spades_exec, bed=bed, work=spades_tmpdir,
                                                       pad=padding, nthreads=sp_opts.num_threads, chrs=contigs,
                                                       max_interval_size=sp_opts.spades_max_interval_size,
                                                       svs_to_assemble=sp_opts.svs_to_assemble,
                                                       stop_on_fail=sp_opts.stop_spades_on_fail,
                                                       max_read_pairs=sp_opts.extraction_max_read_pairs,
                                                       assembly_max_tools=sp_opts.assembly_max_tools, slicing=slicing)
    breakpoints_bed = run_age_parallel(intervals_bed=bed, reference=reference, assembly=assembled_fasta, pad=padding,
                                       age=age_exec, chrs=contigs, nthreads=age_opts.num_threads,
                                       min_contig_len=AGE_MIN_CONTIG_LENGTH, age_window=age_opts.age_window,
                                       min_del_subalign_len=age_opts.min_del_subalign_len,
                                       min_inv_subalign_len=age_opts.min_inv_subalign_len, age_workdir=age_tmpdir)
    final_bed = os.path.join(workdir, "final.bed")
    if breakpoints_bed:
        cat_tool = pybedtools.BedTool(breakpoints_bed)
        if ignored_bed:
            cat_tool = cat_tool.cat(pybedtools.BedTool(ignored_bed), postmerge=False).sort()
        cat_tool.saveas(final_bed)
    elif ignored_bed:
        pybedtools.BedTool(ignored_bed).sort().saveas(final_bed)
    else:
        final_bed = None
    genotyped_bed = parallel_genotype_intervals(final_bed, bam_file, workdir=gt_tmpdir, nthreads=gt_opts.num_threads,
                                                chromosomes=contigs, window=gt_opts.gt_window,
                                                isize_mean=gt_opts.isize_mean, isize_sd=gt_opts.isize_sd,
                                                normal_frac_threshold=gt_opts.gt_normal_frac)
    return genotyped_bed


def run_distributed_assembly(args):
    logger.info("Starting assembly as worker %d / %d" % (args.asm_worker_id, args.asm_fleet))
    contig_whitelist = list(make_contig_whiteset(args, get_contigs(args.reference)))
    if not os.path.isfile(args.asm_bed):
        logger.fatal("BED file of assembly regions does not exist: %s" % args.asm_bed)
        return os.EX_NOINPUT
    out_file = asm_sc_intervals(bed=args.asm_bed, bam_file=args.bam.name, reference=args.reference, sample=args.sample,
                                contigs=contig_whitelist, padding=args.assembly_pad, workdir=args.workdir,
                                spades_exec=args.spades, sp_opts=args, age_exec=args.age, age_opts=args, gt_opts=args,
                                slicing=[args.asm_worker_id, args.asm_fleet])
    logger.info("Done. Wrote genotyped BED file %s" % out_file)
    return os.EX_OK


def run_merge_assembly_slices(args):
    logger.info("Merging %d genotyped BED files from parallel assembly..." % len(args.asm_slices))
    convert_metasv_bed_to_vcf(bedfiles=args.asm_slices, vcf_out=canonical_result_file(args), workdir=args.workdir,
                              sample=args.sample, reference=args.reference, pass_calls=False)
    return os.EX_OK
