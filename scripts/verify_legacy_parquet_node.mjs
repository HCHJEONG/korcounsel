// Analysis-only: package root is explicit; no frontend/runtime dependency.
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { resolve, join } from 'node:path';
import { isDeepStrictEqual } from 'node:util';

const [directory, packageRoot, reportPath] = process.argv.slice(2);
const require = createRequire(join(resolve(packageRoot), 'package.json'));
const { DuckDBInstance } = require('@duckdb/node-api');
const version = require('@duckdb/node-api/package.json').version;
const manifest = JSON.parse(readFileSync(join(directory, 'manifest.json'), 'utf8'));
const expectedBytes = readFileSync(join(directory, 'expected.json'));
const parquet = readFileSync(join(directory, 'sample.parquet'));
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
if (hash(parquet) !== manifest.parquet_sha256 ||
    hash(expectedBytes) !== manifest.expected_sha256) throw new Error('INPUT_HASH_MISMATCH');
const expected = JSON.parse(expectedBytes);
const instance = await DuckDBInstance.create(':memory:');
const connection = await instance.connect();
const started = performance.now();
try {
  const reader = await connection.runAndReadAll(
    'SELECT * FROM read_parquet(?) ORDER BY "__legacy_position"',
    [resolve(directory, 'sample.parquet')],
  );
  const rows = reader.getRowObjectsJson();
  if (rows.length !== expected.length) throw new Error('ROW_COUNT_MISMATCH');
  for (let i = 0; i < rows.length; i++) {
    if (!isDeepStrictEqual(rows[i], expected[i])) throw new Error('CELL_MISMATCH_AT_ROW_' + i);
  }
  const first = manifest.schema.columns[0];
  const quoted = '"' + first.replaceAll('"', '""') + '"';
  const selected = await connection.runAndReadAll(
    'SELECT ' + quoted + ' FROM read_parquet(?) ORDER BY "__legacy_position"',
    [resolve(directory, 'sample.parquet')],
  );
  if (!isDeepStrictEqual(selected.getRowObjectsJson(), expected.map(row => ({ [first]: row[first] })))) {
    throw new Error('SELECTED_COLUMN_MISMATCH');
  }
  const report = {
    node: process.version, duckdb_node_api: version,
    parquet_sha256: manifest.parquet_sha256,
    rows: rows.length, original_columns: manifest.columns,
    all_cells_equal: true, selected_column_equal: true,
    elapsed_ms: performance.now() - started, peak_rss_bytes: process.resourceUsage().maxRSS * 1024,
    bigint_policy: 'DuckDB JSON decimal strings, no conversion to JavaScript Number',
  };
  writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report));
} finally {
  connection.closeSync();
  instance.closeSync();
}
