// Analysis-only Node/DuckDB validation for the corrected 60-column legacy Parquet.
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';

const [directory, packageRoot, reportPath] = process.argv.slice(2);
if (!directory || !packageRoot || !reportPath) {
  throw new Error('USAGE: node verify_corrected_legacy_parquet_node.mjs DIRECTORY PACKAGE_ROOT REPORT');
}

const require = createRequire(join(resolve(packageRoot), 'package.json'));
const { DuckDBInstance } = require('@duckdb/node-api');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');

const manifest = JSON.parse(readFileSync(join(directory, 'manifest.json'), 'utf8'));
const parquetPath = resolve(directory, 'legacy-corrected-full.parquet');
const parquetHash = hash(readFileSync(parquetPath));
if (parquetHash !== manifest.parquet.sha256) {
  throw new Error('PARQUET_HASH_MISMATCH');
}

const instance = await DuckDBInstance.create(':memory:');
const connection = await instance.connect();
try {
  const summaryReader = await connection.runAndReadAll(
    `SELECT
       count(*) AS row_count,
       count(*) FILTER (WHERE decision_date.encoding = 'JSON') AS decision_json,
       count(*) FILTER (WHERE closing_argument.encoding = 'JSON') AS closing_json,
       count(*) FILTER (WHERE closing_argument.encoding = 'STRING') AS closing_string,
       min(__legacy_position) AS min_position,
       max(__legacy_position) AS max_position
     FROM read_parquet(?)`,
    [parquetPath],
  );
  const summary = summaryReader.getRowsJson()[0];
  const rowCount = Number(summary[0]);
  const decisionJson = Number(summary[1]);
  const closingJson = Number(summary[2]);
  const closingString = Number(summary[3]);
  const minPosition = Number(summary[4]);
  const maxPosition = Number(summary[5]);
  const columnReader = await connection.runAndReadAll(
    `SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet(?))`,
    [parquetPath],
  );
  const columns = columnReader.getRowsJson().map(row => row[0]);
  const expectedColumnCount = manifest.columns + 2;
  if (rowCount !== manifest.rows) throw new Error('ROW_COUNT_MISMATCH');
  if (columns.length !== expectedColumnCount) throw new Error('COLUMN_COUNT_MISMATCH');
  if (decisionJson !== manifest.repairs_applied.decision_date) {
    throw new Error('DECISION_DATE_ENCODING_MISMATCH');
  }
  if (closingJson !== 13563) throw new Error('CLOSING_DATE_ENCODING_MISMATCH');
  if (minPosition !== 0 || maxPosition !== manifest.rows - 1) {
    throw new Error('POSITION_RANGE_MISMATCH');
  }
  const result = {
    scope: 'FULL_CORRECTED_LEGACY_PARQUET_NODE_CHECK',
    rows: rowCount,
    columns: columns.length,
    legacy_columns: manifest.columns,
    parquet_sha256: parquetHash,
    decision_date_json_rows: decisionJson,
    closing_argument_json_rows: closingJson,
    closing_argument_string_rows: closingString,
    position_range: [minPosition, maxPosition],
    node: process.version,
    duckdb_node_api: require('@duckdb/node-api/package.json').version,
    check_passed: true,
  };
  writeFileSync(reportPath, JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
} finally {
  connection.closeSync();
  instance.closeSync();
}


