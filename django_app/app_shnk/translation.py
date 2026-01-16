from modeltranslation.translator import translator, TranslationOptions
from .models import (
        Shnk, Qurilish_reglaament, Malumotnoma, 
        Subsystem, ShnkGroup, SREN, SREN_SHNQ, 
        Texnik_reglaament, Standard, ShnkGroupInformation, ShnkInformation
)



class ShnkGroupInformationTranslationOptions(TranslationOptions):
    fields = ('title',)
translator.register(ShnkGroupInformation, ShnkGroupInformationTranslationOptions)


class ShnkInformationTranslationOptions(TranslationOptions):
    fields = ('name',)
translator.register(ShnkInformation, ShnkInformationTranslationOptions)

class StandardTranslationOptions(TranslationOptions):
    fields = ('title', 'designation')


translator.register(Standard, StandardTranslationOptions)


class SubsystemTranslationOptions(TranslationOptions):
    fields = ('title',)

translator.register(Subsystem, SubsystemTranslationOptions)


class ShnkGroupTranslationOptions(TranslationOptions):
    fields = ('title',)

translator.register(ShnkGroup, ShnkGroupTranslationOptions)


class ShnkTranslationOptions(TranslationOptions):
    fields = ('name',)

translator.register(Shnk, ShnkTranslationOptions)


class Qurilish_reglaamentTranslationOptions(TranslationOptions):
    fields = ('group','name',)

translator.register(Qurilish_reglaament, Qurilish_reglaamentTranslationOptions)


class Texnik_reglaamentTranslationOptions(TranslationOptions):
    fields = ('name',)

translator.register(Texnik_reglaament, Texnik_reglaamentTranslationOptions)


class MalumotnomaTranslationOptions(TranslationOptions):
    fields = ('name',)

translator.register(Malumotnoma, MalumotnomaTranslationOptions)


class SRENTranslationOptions(TranslationOptions):
    fields = ('name',)

translator.register(SREN, SRENTranslationOptions)

class SREN_SHNQTranslationOptions(TranslationOptions):
    fields = ('name',)

translator.register(SREN_SHNQ, SREN_SHNQTranslationOptions)