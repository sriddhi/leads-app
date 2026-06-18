import React from 'react';

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
}

// forwardRef is required so react-hook-form's `register` ref attaches to the real
// <input>. Without it the ref is dropped and RHF can't read autofilled/pasted values
// (fields look filled but validate as empty → false "required" errors + blocked submit).
const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, error, id, className = '', ...props },
  ref
) {
  const inputId = id ?? label.toLowerCase().replace(/\s+/g, '-');

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={inputId} className="text-sm font-medium text-gray-700">
        {label}
      </label>
      <input
        id={inputId}
        ref={ref}
        className={`rounded-md border px-3 py-2 text-sm shadow-sm outline-none transition-colors focus:border-blue-500 focus:ring-1 focus:ring-blue-500 ${
          error ? 'border-red-500' : 'border-gray-300'
        } ${className}`}
        {...props}
      />
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
});

export default Input;
