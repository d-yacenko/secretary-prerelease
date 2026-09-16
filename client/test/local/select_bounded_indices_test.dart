import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/local/extraction/representation_builder.dart';

void _assertContract(List<int> indices, int total, int maxChunks) {
  expect(indices.length, lessThanOrEqualTo(maxChunks));
  expect(indices.toSet().length, indices.length);
  final sorted = List<int>.from(indices)..sort();
  expect(indices, sorted);
  for (final index in indices) {
    expect(index, inInclusiveRange(0, total - 1));
  }
}

void main() {
  for (final total in [1, 2, 3, 4, 5, 10, 11, 100, 101]) {
    for (final maxChunks in [1, 2, 3, 4, 5, 8, 16, 32, 64]) {
      test('selectBoundedIndices contract total=$total maxChunks=$maxChunks', () {
        final first = selectBoundedIndices(total, maxChunks);
        final second = selectBoundedIndices(total, maxChunks);
        _assertContract(first, total, maxChunks);
        expect(first, second);
      });
    }
  }

  test('maxChunks=3 keeps exactly one middle for even total', () {
    expect(selectBoundedIndices(10, 3), [0, 5, 9]);
  });

  test('maxChunks=3 keeps exactly one middle for odd total', () {
    expect(selectBoundedIndices(11, 3), [0, 5, 10]);
  });

  test('maxChunks=2 keeps begin and end only', () {
    expect(selectBoundedIndices(100, 2), [0, 99]);
  });

  test('maxChunks=4 includes distributed coverage', () {
    final indices = selectBoundedIndices(100, 4);
    expect(indices.length, 4);
    expect(indices.first, 0);
    expect(indices.last, 99);
    expect(indices, contains(50));
  });

  test('near-total capacity keeps all indices', () {
    expect(selectBoundedIndices(5, 8), [0, 1, 2, 3, 4]);
  });
}
