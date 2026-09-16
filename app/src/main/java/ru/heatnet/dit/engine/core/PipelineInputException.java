package ru.heatnet.dit.engine.core;

/** Входной файл не соответствует конкурсной схеме (диагностическая ошибка, п.9). */
public class PipelineInputException extends RuntimeException {
    public PipelineInputException(String message) {
        super(message);
    }
}
