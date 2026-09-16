/// Mechanical local file extraction bounds (PHASE 26B / Format Parity Pass B).
const int kMaxExtractorParts = 64;
const int kMaxExtractorPartBytes = 16 * 1024;
const int kMaxExtractorTotalBytes = 256 * 1024;
const int kSmallTextMaxChars = 500;
const int kChunkSize = 800;
const int kChunkOverlap = 100;
const int kMaxExtractedTextBytes = 2 * 1024 * 1024;
const int kMaxCsvColumns = 100;
const int kMaxCsvStatsRows = 5000;
const int kCheapHashMaxBytes = 256 * 1024;
const int kReadWindowBytes = 8000;
@Deprecated('Use kMaxExtractedTextBytes')
const int kMaxExtractedTextChars = 512000;

const int kMaxPdfPages = 300;
const int kMaxPdfInputBytes = 32 * 1024 * 1024;
const int kMaxOoxmlZipEntries = 512;
const int kMaxOoxmlUncompressedBytes = 32 * 1024 * 1024;
const int kMaxOoxmlCompressionRatio = 200;
const int kMaxXlsxSheets = 16;
const int kMaxXlsxRowsPerSheet = 200;
const int kMaxXlsxColumns = 64;
const int kMaxPptxSlides = 500;
const int kMaxOdfSheets = 16;
const int kMaxOdfRowsPerSheet = 200;
const int kMaxOdfColumns = 64;
const int kMaxOdfRepeatExpansion = 64;
const int kMaxOdpSlides = 500;

const int kDatasetStructuralParts = 3;
const int kCompactSampleMaxRows = 5;
const int kMaxSampledIndexList = 64;

const Set<String> kSupportedModernSuffixes = {
  '.txt',
  '.md',
  '.csv',
  '.pdf',
  '.docx',
  '.xlsx',
  '.pptx',
  '.odt',
  '.ods',
  '.odp',
  '.parquet',
};

const Set<String> kLegacyMetadataOnlySuffixes = {
  '.doc',
  '.xls',
  '.ppt',
};
