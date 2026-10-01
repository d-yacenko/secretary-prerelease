const removableSemanticEdgeTypes = <String>{
  'references',
  'related_to',
  'depends_on',
  'part_of',
  'requested_by',
  'delegated_to',
  'waiting_on',
  'involves',
};

bool agentConfirmedRelationIsRemovable({
  required String origin,
  required String state,
  required String type,
}) {
  return origin == 'agent' && state == 'confirmed' && removableSemanticEdgeTypes.contains(type);
}
