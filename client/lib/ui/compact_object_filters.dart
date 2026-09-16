import 'package:flutter/material.dart';

import '../api/api_models.dart';
import 'object_presentation.dart';

typedef FilterChanged = void Function();

bool _isDesktopFilterContext(BuildContext context) {
  return MediaQuery.sizeOf(context).width >= 600;
}

class CompactObjectFilters extends StatelessWidget {
  const CompactObjectFilters({
    super.key,
    required this.facets,
    required this.selectedKind,
    required this.selectedProvider,
    required this.selectedSort,
    required this.showSort,
    required this.onKindChanged,
    required this.onProviderChanged,
    required this.onSortChanged,
    this.labels = const [],
    this.selectedLabelId,
    this.onLabelChanged,
  });

  final SearchFacetsOut? facets;
  final String? selectedKind;
  final String? selectedProvider;
  final String selectedSort;
  final bool showSort;
  final ValueChanged<String?> onKindChanged;
  final ValueChanged<String?> onProviderChanged;
  final ValueChanged<String> onSortChanged;
  final List<LabelItem> labels;
  final String? selectedLabelId;
  final ValueChanged<String?>? onLabelChanged;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _KindFilterButton(
          facets: facets,
          selectedKind: selectedKind,
          onChanged: onKindChanged,
        ),
        _ProviderFilterButton(
          facets: facets,
          selectedProvider: selectedProvider,
          onChanged: onProviderChanged,
        ),
        if (showSort)
          _SortFilterButton(
            selectedSort: selectedSort,
            onChanged: onSortChanged,
          ),
        if (onLabelChanged != null && labels.isNotEmpty)
          _LabelFilterButton(
            labels: labels,
            selectedLabelId: selectedLabelId,
            onChanged: onLabelChanged!,
          ),
      ],
    );
  }
}

class _KindFilterButton extends StatelessWidget {
  const _KindFilterButton({
    required this.facets,
    required this.selectedKind,
    required this.onChanged,
  });

  final SearchFacetsOut? facets;
  final String? selectedKind;
  final ValueChanged<String?> onChanged;

  @override
  Widget build(BuildContext context) {
    final label = selectedKind == null
        ? 'Все типы'
        : objectKindLabel(selectedKind!);
    final icon = selectedKind == null
        ? Icons.category_outlined
        : iconForObjectKind(selectedKind!);

    if (!_isDesktopFilterContext(context)) {
      return Semantics(
        label: 'Фильтр типа: $label',
        button: true,
        child: Tooltip(
          message: label,
          child: IconButton(
            icon: Icon(icon),
            style: IconButton.styleFrom(
              backgroundColor: selectedKind != null
                  ? Theme.of(context).colorScheme.primaryContainer
                  : null,
            ),
            onPressed: () => _showKindBottomSheet(context),
          ),
        ),
      );
    }

    return MenuAnchor(
      builder: (context, controller, child) {
        return Semantics(
          label: 'Фильтр типа: $label',
          button: true,
          child: Tooltip(
            message: label,
            child: IconButton(
              icon: Icon(icon),
              style: IconButton.styleFrom(
                backgroundColor: selectedKind != null
                    ? Theme.of(context).colorScheme.primaryContainer
                    : null,
              ),
              onPressed: () {
                if (controller.isOpen) {
                  controller.close();
                } else {
                  controller.open();
                }
              },
            ),
          ),
        );
      },
      menuChildren: _kindMenuItems(context),
    );
  }

  List<Widget> _kindMenuItems(BuildContext context) {
    final kinds = facets?.kinds ?? [];
    return [
      MenuItemButton(
        onPressed: () => onChanged(null),
        child: const Text('Все типы'),
      ),
      for (final facet in kinds)
        MenuItemButton(
          onPressed: () => onChanged(facet.value),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(iconForObjectKind(facet.value), size: 18),
              const SizedBox(width: 8),
              Text(objectKindLabel(facet.value)),
            ],
          ),
        ),
    ];
  }

  void _showKindBottomSheet(BuildContext context) {
    final kinds = facets?.kinds ?? [];
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Wrap(
          spacing: 8,
          runSpacing: 8,
          alignment: WrapAlignment.center,
          children: [
            _FacetChoice(
              tooltip: 'Все типы',
              semanticsLabel: 'Все типы',
              selected: selectedKind == null,
              icon: Icons.clear_all,
              onTap: () {
                onChanged(null);
                Navigator.pop(context);
              },
            ),
            for (final facet in kinds)
              _FacetChoice(
                tooltip: objectKindLabel(facet.value),
                semanticsLabel: objectKindLabel(facet.value),
                selected: selectedKind == facet.value,
                icon: iconForObjectKind(facet.value),
                onTap: () {
                  onChanged(facet.value);
                  Navigator.pop(context);
                },
              ),
          ],
        ),
      ),
    );
  }
}

class _ProviderFilterButton extends StatelessWidget {
  const _ProviderFilterButton({
    required this.facets,
    required this.selectedProvider,
    required this.onChanged,
  });

  final SearchFacetsOut? facets;
  final String? selectedProvider;
  final ValueChanged<String?> onChanged;

  @override
  Widget build(BuildContext context) {
    final label = selectedProvider == null
        ? 'Все источники'
        : providerLabel(selectedProvider);

    if (!_isDesktopFilterContext(context)) {
      return Semantics(
        label: 'Фильтр источника: $label',
        button: true,
        child: Tooltip(
          message: label,
          child: IconButton(
            icon: selectedProvider == null
                ? const Icon(Icons.storage_outlined)
                : providerCompactIcon(selectedProvider),
            style: IconButton.styleFrom(
              backgroundColor: selectedProvider != null
                  ? Theme.of(context).colorScheme.primaryContainer
                  : null,
            ),
            onPressed: () => _showProviderBottomSheet(context),
          ),
        ),
      );
    }

    return MenuAnchor(
      builder: (context, controller, child) {
        return Semantics(
          label: 'Фильтр источника: $label',
          button: true,
          child: Tooltip(
            message: label,
            child: IconButton(
              icon: selectedProvider == null
                  ? const Icon(Icons.storage_outlined)
                  : providerCompactIcon(selectedProvider),
              style: IconButton.styleFrom(
                backgroundColor: selectedProvider != null
                    ? Theme.of(context).colorScheme.primaryContainer
                    : null,
              ),
              onPressed: () {
                if (controller.isOpen) {
                  controller.close();
                } else {
                  controller.open();
                }
              },
            ),
          ),
        );
      },
      menuChildren: _providerMenuItems(context),
    );
  }

  List<Widget> _providerMenuItems(BuildContext context) {
    final providers = facets?.providers ?? [];
    return [
      MenuItemButton(
        onPressed: () => onChanged(null),
        child: const Text('Все источники'),
      ),
      for (final facet in providers)
        MenuItemButton(
          onPressed: () => onChanged(facet.value),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              providerCompactIcon(facet.value),
              const SizedBox(width: 8),
              Text(providerLabel(facet.value)),
            ],
          ),
        ),
    ];
  }

  void _showProviderBottomSheet(BuildContext context) {
    final providers = facets?.providers ?? [];
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Wrap(
          spacing: 8,
          runSpacing: 8,
          alignment: WrapAlignment.center,
          children: [
            _FacetChoice(
              tooltip: 'Сбросить фильтр',
              semanticsLabel: 'Все источники',
              selected: selectedProvider == null,
              icon: Icons.clear_all,
              onTap: () {
                onChanged(null);
                Navigator.pop(context);
              },
            ),
            for (final facet in providers)
              _FacetChoice(
                tooltip: providerLabel(facet.value),
                semanticsLabel: providerLabel(facet.value),
                selected: selectedProvider == facet.value,
                child: providerCompactIcon(facet.value),
                onTap: () {
                  onChanged(facet.value);
                  Navigator.pop(context);
                },
              ),
          ],
        ),
      ),
    );
  }
}

class _SortFilterButton extends StatelessWidget {
  const _SortFilterButton({
    required this.selectedSort,
    required this.onChanged,
  });

  final String selectedSort;
  final ValueChanged<String> onChanged;

  String _label(String sort) {
    switch (sort) {
      case 'newest':
        return 'Сначала новые';
      case 'oldest':
        return 'Сначала старые';
      default:
        return 'Релевантность';
    }
  }

  @override
  Widget build(BuildContext context) {
    final label = _label(selectedSort);

    if (!_isDesktopFilterContext(context)) {
      return Semantics(
        label: 'Сортировка: $label',
        button: true,
        child: Tooltip(
          message: label,
          child: IconButton(
            icon: const Icon(Icons.sort),
            style: IconButton.styleFrom(
              backgroundColor: selectedSort != 'relevance'
                  ? Theme.of(context).colorScheme.primaryContainer
                  : null,
            ),
            onPressed: () => _showSortBottomSheet(context),
          ),
        ),
      );
    }

    return MenuAnchor(
      builder: (context, controller, child) {
        return Semantics(
          label: 'Сортировка: $label',
          button: true,
          child: Tooltip(
            message: label,
            child: IconButton(
              icon: const Icon(Icons.sort),
              style: IconButton.styleFrom(
                backgroundColor: selectedSort != 'relevance'
                    ? Theme.of(context).colorScheme.primaryContainer
                    : null,
              ),
              onPressed: () {
                if (controller.isOpen) {
                  controller.close();
                } else {
                  controller.open();
                }
              },
            ),
          ),
        );
      },
      menuChildren: [
        MenuItemButton(
          onPressed: () => onChanged('relevance'),
          child: const Text('Релевантность'),
        ),
        MenuItemButton(
          onPressed: () => onChanged('newest'),
          child: const Text('Сначала новые'),
        ),
        MenuItemButton(
          onPressed: () => onChanged('oldest'),
          child: const Text('Сначала старые'),
        ),
      ],
    );
  }

  void _showSortBottomSheet(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.star_outline),
              title: const Text('Релевантность'),
              selected: selectedSort == 'relevance',
              onTap: () {
                onChanged('relevance');
                Navigator.pop(context);
              },
            ),
            ListTile(
              leading: const Icon(Icons.arrow_downward),
              title: const Text('Сначала новые'),
              selected: selectedSort == 'newest',
              onTap: () {
                onChanged('newest');
                Navigator.pop(context);
              },
            ),
            ListTile(
              leading: const Icon(Icons.arrow_upward),
              title: const Text('Сначала старые'),
              selected: selectedSort == 'oldest',
              onTap: () {
                onChanged('oldest');
                Navigator.pop(context);
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _LabelFilterButton extends StatelessWidget {
  const _LabelFilterButton({
    required this.labels,
    required this.selectedLabelId,
    required this.onChanged,
  });

  final List<LabelItem> labels;
  final String? selectedLabelId;
  final ValueChanged<String?> onChanged;

  String get _selectedTitle {
    if (selectedLabelId == null) {
      return 'Все';
    }
    for (final label in labels) {
      if (label.id == selectedLabelId) {
        return label.title;
      }
    }
    return 'Все';
  }

  @override
  Widget build(BuildContext context) {
    final display = 'Метка: $_selectedTitle';
    if (!_isDesktopFilterContext(context)) {
      return Semantics(
        label: display,
        button: true,
        child: Tooltip(
          message: display,
          child: IconButton(
            key: const Key('search_label_filter'),
            icon: const Icon(Icons.label_outline),
            style: IconButton.styleFrom(
              backgroundColor: selectedLabelId != null
                  ? Theme.of(context).colorScheme.primaryContainer
                  : null,
            ),
            onPressed: () => _showSheet(context),
          ),
        ),
      );
    }

    return MenuAnchor(
      builder: (context, controller, child) {
        return Semantics(
          label: display,
          button: true,
          child: Tooltip(
            message: display,
            child: IconButton(
              key: const Key('search_label_filter'),
              icon: const Icon(Icons.label_outline),
              style: IconButton.styleFrom(
                backgroundColor: selectedLabelId != null
                    ? Theme.of(context).colorScheme.primaryContainer
                    : null,
              ),
              onPressed: () {
                if (controller.isOpen) {
                  controller.close();
                } else {
                  controller.open();
                }
              },
            ),
          ),
        );
      },
      menuChildren: [
        MenuItemButton(
          onPressed: () => onChanged(null),
          child: const Text('Метка: Все'),
        ),
        for (final label in labels)
          MenuItemButton(
            onPressed: () => onChanged(label.id),
            child: Text(label.title),
          ),
      ],
    );
  }

  void _showSheet(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) {
        final maxHeight = MediaQuery.sizeOf(context).height * 0.7;
        return SafeArea(
          child: ConstrainedBox(
            constraints: BoxConstraints(maxHeight: maxHeight),
            child: ListView(
              key: const Key('search_label_filter_sheet'),
              shrinkWrap: true,
              children: [
                ListTile(
                  title: const Text('Метка: Все'),
                  selected: selectedLabelId == null,
                  onTap: () {
                    onChanged(null);
                    Navigator.pop(context);
                  },
                ),
                for (final label in labels)
                  ListTile(
                    title: Text(label.title),
                    selected: selectedLabelId == label.id,
                    onTap: () {
                      onChanged(label.id);
                      Navigator.pop(context);
                    },
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _FacetChoice extends StatelessWidget {
  const _FacetChoice({
    required this.tooltip,
    required this.semanticsLabel,
    required this.selected,
    required this.onTap,
    this.icon,
    this.child,
  });

  final String tooltip;
  final String semanticsLabel;
  final bool selected;
  final VoidCallback onTap;
  final IconData? icon;
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: semanticsLabel,
      selected: selected,
      button: true,
      child: Tooltip(
        message: tooltip,
        child: Material(
          color: selected
              ? Theme.of(context).colorScheme.primaryContainer
              : Theme.of(context).colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(12),
          child: InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(12),
            child: SizedBox(
              width: 48,
              height: 48,
              child: Center(
                child: child ?? Icon(icon),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
