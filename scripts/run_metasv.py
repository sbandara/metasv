#!/usr/bin/env python

import sys
import argparse
from metasv.main import run_metasv, run_distributed_assembly, run_merge_assembly_slices
from metasv.defaults import *
from metasv._version import __version__
import logging

FORMAT = '%(levelname)s %(asctime)-15s %(name)-20s %(message)s'
logging.basicConfig(level=logging.INFO, format=FORMAT)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge SVs from multiple tools for accurate SV calling",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    input_parser = parser.add_argument_group("Input data options")
    input_parser.add_argument("--sample", metavar="Sample", help="Sample name", required=True)
    input_parser.add_argument("--pindel_vcf", nargs="+", metavar="pindel_vcf", help="VCF file or dir for Pindel VCFs",
                              required=False, default=[])
    input_parser.add_argument("--pindel_native", nargs="+", metavar="File list", help="Pindel native files",
                              required=False,
                              default=[])
    input_parser.add_argument("--breakdancer_vcf", nargs="+", metavar="breakdancer_vcf",
                              help="VCF file or dir for BreakDancer VCFs", required=False, default=[])
    input_parser.add_argument("--breakdancer_native", nargs="+", metavar="File list", help="BreakDancer native files",
                              required=False, default=[])
    input_parser.add_argument("--breakseq_vcf", nargs="+", metavar="breakseq_vcf",
                              help="VCF file or dir for BreakSeq VCFs",
                              required=False, default=[])
    input_parser.add_argument("--breakseq_native", nargs="+", metavar="breakseq_native",
                              help="BreakSeq native GFF files",
                              required=False, default=[])
    input_parser.add_argument("--cnvnator_vcf", nargs="+", metavar="cnvnator_vcf",
                              help="VCF file or dir for CNVnator VCFs",
                              required=False, default=[])
    input_parser.add_argument("--cnvnator_native", nargs="+", metavar="File list", help="CNVnator native files",
                              required=False,
                              default=[])
    input_parser.add_argument("--gatk_vcf", nargs="+", metavar="file", help="VCF file or dir for gatk VCFs",
                              required=False,
                              default=[])
    input_parser.add_argument("--manta_vcf", nargs="+", help="VCF file or dir for Manta VCFs",
                              required=False, default=[])
    input_parser.add_argument("--lumpy_vcf", nargs="+", help="VCF file or dir for Lumpy VCFs",
                              required=False, default=[])
    input_parser.add_argument("--cnvkit_vcf", nargs="+", help="VCF file or dir for CNVkit VCFs",
                              required=False, default=[])
    input_parser.add_argument("--wham_vcf", nargs="+", help="VCF file or dir for WHAM VCFs",
                              required=False, default=[])
                              
    input_parser.add_argument("--mean_read_length", type=float, default=MEAN_READ_LENGTH, help="Mean read length")

    reference_parser = parser.add_argument_group("Reference options")
    reference_parser.add_argument("--reference", metavar="reference", help="Reference file", required=True)
    reference_parser.add_argument("--chromosomes",
                                  help="Chromosome list to process. If unspecified, then all chromosomes will be considered.",
                                  nargs="+", default=[])
    reference_parser.add_argument("--gaps", metavar="gaps", help="Gap bed file", required=False, default=None)
    reference_parser.add_argument("--filter_gaps", help="Filter out gaps", action="store_true", required=False)
    reference_parser.add_argument("--keep_standard_contigs", action="store_true",
                                  help="Keep only the major contigs + MT")

    bam_parser = parser.add_argument_group("Input BAM options")
    bam_parser.add_argument("--bam", help="BAM", type=file)
    bam_parser.add_argument("--isize_mean", type=float, default=ISIZE_MEAN, help="Insert size mean")
    bam_parser.add_argument("--isize_sd", type=float, default=ISIZE_SD, help="Insert size standard deviation")

    merging_parser = parser.add_argument_group("Tool output merging options")
    merging_parser.add_argument("--wiggle", help="Wiggle for interval overlap", default=WIGGLE, type=int,
                                required=False)
    merging_parser.add_argument("--inswiggle", help="Wiggle for insertions, overides wiggle", default=INS_WIGGLE,
                                type=int,
                                required=False)
    merging_parser.add_argument("--minsvlen", help="Minimum length acceptable to be an SV", default=MIN_SV_LENGTH,
                                type=int,
                                required=False)
    merging_parser.add_argument("--maxsvlen", help="Maximum length SV to report", default=MAX_SV_LENGTH,
                                type=int,
                                required=False)
    merging_parser.add_argument("--overlap_ratio", help="Reciprocal overlap ratio", default=OVERLAP_RATIO, type=float,
                                required=False)

    insertion_parser = parser.add_argument_group("Insertion detection options")
    insertion_parser.add_argument("--min_avg_base_qual", help="Minimum average base quality",
                                  default=SC_MIN_AVG_BASE_QUAL, type=int)
    insertion_parser.add_argument("--min_mapq", help="Minimum MAPQ", default=SC_MIN_MAPQ, type=int)
    insertion_parser.add_argument("--min_soft_clip", help="Minimum soft-clip", default=SC_MIN_SOFT_CLIP, type=int)
    insertion_parser.add_argument("--max_nm", help="Maximum number of edits", default=SC_MAX_NM, type=int)
    insertion_parser.add_argument("--min_matches", help="Mininum number of matches", default=SC_MIN_MATCHES, type=int)
    insertion_parser.add_argument("--min_support_ins",
                                  help="Minimum read support for calling insertions using soft-clips (including neighbors)",
                                  type=int, default=MIN_SUPPORT_INS)
    insertion_parser.add_argument("--min_support_frac_ins",
                                  help="Minimum fraction of reads supporting insertion using soft-clips (including neighbors)", type=float,
                                  default=MIN_SUPPORT_FRAC_INS)
    insertion_parser.add_argument("--max_ins_intervals", help="Maximum number of insertion intervals to generate",
                                  type=int,
                                  default=MAX_INTERVALS)
    insertion_parser.add_argument("--mean_read_coverage", type=float, default=MEAN_READ_COVERAGE, help="Mean read coverage")
    insertion_parser.add_argument("--min_ins_cov_frac", type=float, default=MIN_INS_COVERAGE_FRAC, help="Minimum read coverage around the insertion breakpoint.")
    insertion_parser.add_argument("--max_ins_cov_frac", type=float, default=MAX_INS_COVERAGE_FRAC, help="Maximum read coverage around the insertion breakpoint.")

    as_parser = parser.add_argument_group("Assembly options")
    as_parser.add_argument("--spades", help="Path to SPAdes executable", required=False)
    as_parser.add_argument("--disable_assembly", action="store_true", help="Disable assembly (deprecated)")
    as_parser.add_argument("--assembly", choices=ASM_RUN_MODES, default=ASM_FULL, help="Assembly execution plan")
    as_parser.add_argument("--asm_fleet", help="Total number of workers used for parallel execution of assembly", type=int)
    as_parser.add_argument("--asm_worker_id", help="Zero-based worker ID for contributing to parallel assembly", type=int)
    as_parser.add_argument("--asm_bed", help="BED file of regions to assemble when --assembly=%s" % ASM_SLICED)
    as_parser.add_argument("--asm_slices", help="Genotyped BED slices to be merged into final VCF.", nargs="+", default=[])
    as_parser.add_argument("--svs_to_assemble", nargs="+", help="SVs to assemble", default=SVS_ASSEMBLY_SUPPORTED,
                           choices=SVS_ASSEMBLY_SUPPORTED)
    as_parser.add_argument("--svs_to_softclip", nargs="+", help="SVs to soft-clip", default=SVS_SOFTCLIP_SUPPORTED,
                           choices=SVS_SOFTCLIP_SUPPORTED)
    as_parser.add_argument("--extraction_max_read_pairs", type=int, default=EXTRACTION_MAX_READ_PAIRS,
                           help="Maximum number of pairs to extract for assembly")
    as_parser.add_argument("--spades_max_interval_size", type=int, default=SPADES_MAX_INTERVAL_SIZE,
                           help="Maximum SV length for assembly")
    as_parser.add_argument("--assembly_max_tools", type=int, default=ASSEMBLY_MAX_TOOLS,
                           help="Skip assembly if more than this many tools support a call (default 1)")
    as_parser.add_argument("--assembly_pad", type=int, default=SPADES_PAD,
                           help="Padding base pairs to use for assembling breakpoint with Spades and AGE")
    as_parser.add_argument("--stop_spades_on_fail", action="store_true", help="Abort on SPAdes failure")
    as_parser.add_argument("--age", help="Path to AGE executable", required=False)
    as_parser.add_argument("--min_inv_subalign_len", help="Minimum length of inversion sub-alginment", type=int,
                        default=MIN_INV_SUBALIGN_LENGTH)
    as_parser.add_argument("--min_del_subalign_len", help="Minimum length of deletion sub-alginment", type=int,
                        default=MIN_DEL_SUBALIGN_LENGTH)
    as_parser.add_argument("--age_window", help="Window size for AGE to merge nearby breakpoints", type=int,
                        default=AGE_WINDOW_SIZE)
    as_parser.add_argument("--boost_sc", help="Use soft-clips for improving breakpoint detection",
                                  action="store_true")
    gt_parser = parser.add_argument_group("Genotyping options")
    gt_parser.add_argument("--gt_window", type=int, default=GT_WINDOW, help="Window for genotyping")
    gt_parser.add_argument("--gt_normal_frac", type=float, default=GT_NORMAL_FRAC,
                           help="Min. fraction of reads supporting reference for genotyping")

    out_parser = parser.add_argument_group("Output options")
    out_parser.add_argument("--svs_to_report", nargs="+", help="SV types to report", default=SVS_SUPPORTED,
                            choices=SVS_SUPPORTED)
    out_parser.add_argument("--enable_per_tool_output", action="store_true",
                            help="Enable output of merged SVs for individual tools")

    work_parser = parser.add_argument_group("Running environment options")
    work_parser.add_argument("--workdir", help="Scratch directory for working", default="work", required=False)
    work_parser.add_argument("--num_threads", help="Number of threads to use", type=int, default=1)
    work_parser.add_argument("--outdir", help="Output directory", required=True)

    other_parser = parser.add_argument_group("Other options")
    other_parser.add_argument('--version', action='version', version='%(prog)s ' + __version__)

    args = parser.parse_args()

    if args.disable_assembly:
        if args.assembly != ASM_DISABLE:
            parser.error("Deprecated argument --disable_assembly contradicts --assembly=%s." % args.assembly)
        else:
            args.assembly = ASM_DISABLE
            logger.warn("Argument --disable_assembly is deprecated. Use --assembly=%s instead." % ASM_DISABLE)

    args.svs_to_assemble = set(args.svs_to_assemble) & set(args.svs_to_report)
    args.svs_to_softclip = set(args.svs_to_softclip) & set(args.svs_to_report)

    if args.assembly == ASM_SLICED:
        if args.asm_worker_id is None:
            parser.error("Missing argument --asm_worker_id for --assembly=%s." % ASM_SLICED)
        if args.asm_fleet is None:
            parser.error("Missing argument --asm_fleet for --assembly=%s." % ASM_SLICED)
        if args.asm_bed is None:
            parser.error("Missing argument --asm_bed for run mode --assembly=%s." % ASM_SLICED)
        if args.asm_worker_id >= args.asm_fleet:
            parser.error("Worker ID --asm_worker_id exceeds fleet size --asm_fleet.")
        sys.exit(run_distributed_assembly(args))
    elif args.assembly == ASM_MERGE:
        if not args.asm_slices:
            parser.error("No input BED files specified by --asm_slices for --assembly=%s" % ASM_MERGE)
        sys.exit(run_merge_assembly_slices(args))
    else:
        sys.exit(run_metasv(args))
