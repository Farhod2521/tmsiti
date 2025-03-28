from modeltranslation.translator import translator, TranslationOptions
from .models import Shnk, Qurilish_reglaament, Malumotnoma, Subsystem, ShnkGroup


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


class MalumotnomaTranslationOptions(TranslationOptions):
    fields = ('name',)

translator.register(Malumotnoma, MalumotnomaTranslationOptions)