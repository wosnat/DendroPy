
# When explicitly reading into
# a CharacterMatrix of a particular
# type, the `data_type` argument
# is not needed.
d = dendropy.DnaCharacterMatrix(
        "data.dat",
        "phylip",
        taxon_set=None,
        strict=False,
        interleaved=False,
        multispace_delimiter=False,
        underscores_to_spaces=False,
        ignore_invalid_chars=Fa;se)

# Otherwise ...
d = dendropy.DataSet(
        "data.dat",
        "phylip",
        taxon_set=None,
        datatype="dna",
        strict=False,
        interleaved=False,
        multispace_delimiter=False,
        underscores_to_spaces=False,
        ignore_invalid_chars=Fa;se)

# Or ..
d = dendropy.DataSet(
        "data.dat",
        "phylip",
        taxon_set=None,
        char_matrix_type=dendropy.DnaCharacterMatrix,
        strict=False,
        interleaved=False,
        multispace_delimiter=False,
        underscores_to_spaces=False,
        ignore_invalid_chars=Fa;se)

